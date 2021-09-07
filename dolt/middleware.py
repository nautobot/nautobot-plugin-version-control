from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection
from django.db.models.signals import m2m_changed, post_save, pre_delete
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.safestring import mark_safe

from health_check.db.models import TestModel

from nautobot.extras.models.change_logging import ObjectChange

from dolt.constants import (
    DOLT_BRANCH_KEYWORD,
    DOLT_DEFAULT_BRANCH,
)
from dolt.versioning import query_on_branch
from dolt.models import Branch, Commit, PullRequest, PullRequestReview
from dolt.utils import DoltError, is_dolt_model


def dolt_health_check_intercept_middleware(get_response):
    """
    Intercept health check calls and disregard
    TODO: fix health-check and remove
    """

    def middleware(request):
        if is_health_check(request):
            return HttpResponse(status=201)
        return get_response(request)

    return middleware


class DoltBranchMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        branch = self.get_branch(request)
        try:
            branch.checkout()
        except Exception as e:
            msg = f"could not checkout branch {branch}: {str(e)}"
            messages.error(request, mark_safe(msg))

        if request.user.is_authenticated:
            # inject the "active branch" banner
            msg = f"""
                <div class="text-center">
                    Active Branch: {Branch.active_branch()}
                </div>
            """
            messages.info(request, mark_safe(msg))

        try:
            return view_func(request, *view_args, **view_kwargs)
        except DoltError as e:
            messages.error(request, mark_safe(e))
            return redirect(request.path)

    def get_branch(self, request):
        # lookup the active branch in the session cookie
        requested = branch_from_request(request)
        try:
            return Branch.objects.get(pk=requested)
        except ObjectDoesNotExist:
            messages.warning(
                request,
                mark_safe(
                    f"""<div class="text-center">branch not found: {requested}</div>"""
                ),
            )
            request.session[DOLT_BRANCH_KEYWORD] = DOLT_DEFAULT_BRANCH
            return Branch.objects.get(pk=DOLT_DEFAULT_BRANCH)


class DoltAutoCommitMiddleware(object):
    """
    adapted from nautobot.extras.middleware.ObjectChangeMiddleware
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Process the request with auto-dolt-commit enabled
        branch = branch_from_request(request)
        with AutoDoltCommit(request, branch):
            return self.get_response(request)


class AutoDoltCommit(object):
    """
    adapted from `nautobot.extras.context_managers`
    """

    def __init__(self, request, branch):
        self.request = request
        self.branch = branch
        self.commit = False
        self.changes = []
        self.instances = []

    def __enter__(self):
        # Connect our receivers to the post_save and post_delete signals.
        post_save.connect(self._handle_update, dispatch_uid="dolt_commit_update")
        m2m_changed.connect(self._handle_update, dispatch_uid="dolt_commit_update")
        pre_delete.connect(self._handle_delete, dispatch_uid="dolt_commit_delete")

    def __exit__(self, type, value, traceback):
        if is_health_check(self.request):
            # don't autocommit django-health-checks
            return

        if self.commit:
            self._commit()

        # Disconnect change logging signals. This is necessary to avoid recording any errant
        # changes during test cleanup.
        post_save.disconnect(self._handle_update, dispatch_uid="dolt_commit_update")
        m2m_changed.disconnect(self._handle_update, dispatch_uid="dolt_commit_update")
        pre_delete.disconnect(self._handle_delete, dispatch_uid="dolt_commit_delete")

    def _handle_update(self, sender, instance, **kwargs):
        """
        Fires when an object is created or updated.
        """

        if is_dolt_model(type(instance)):
            # Dolt plugin objects are always written to "main"
            self.branch = DOLT_DEFAULT_BRANCH
            self.changes.append(self.change_msg_for_dolt_obj(instance, kwargs))

        if type(instance) == ObjectChange:
            self.changes.append(str(instance))

        if "created" in kwargs:
            self.commit = True
        elif kwargs.get("action") in ["post_add", "post_remove"] and kwargs["pk_set"]:
            # m2m_changed with objects added or removed
            self.commit = True

    def _handle_delete(self, sender, instance, **kwargs):
        """
        Fires when an object is deleted.
        """
        self.commit = True

    def _commit(self):
        msg = self._get_commit_message()
        Commit(message=msg).save(
            branch=self.branch,
            user=self.request.user,
        )

    def _get_commit_message(self):
        if self.changes:
            return "; ".join(self.changes)
        elif self.instances:
            return "; ".join([str(i) for i in self.instances])
        return "auto dolt commit"

    @staticmethod
    def change_msg_for_dolt_obj(instance, kwargs):
        created = "created" in kwargs and kwargs["created"]
        verb = "Created" if created else "Updated"
        return f"""{verb} {instance._meta.verbose_name} "{instance}" """


def branch_from_request(request):
    if DOLT_BRANCH_KEYWORD in request.session:
        return request.session.get(DOLT_BRANCH_KEYWORD)
    if DOLT_BRANCH_KEYWORD in request.headers:
        return request.headers.get(DOLT_BRANCH_KEYWORD)
    return DOLT_DEFAULT_BRANCH


def is_health_check(request):
    return "/health" in request.path
