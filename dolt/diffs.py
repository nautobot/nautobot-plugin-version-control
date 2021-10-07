"""Diffs.py contains a set of utilities for producing Dolt diffs."""

from django.contrib.contenttypes.models import ContentType
from django.db import connection, models
from django.db.models import F, Subquery, OuterRef, Value

from nautobot.dcim.tables import cables, devices, devicetypes, power, racks, sites
from nautobot.circuits import tables as circuits_tables
from nautobot.ipam import tables as ipam_tables
from nautobot.tenancy import tables as tenancy_tables
from nautobot.virtualization import tables as virtualization_tables

from dolt.dynamic.diff_factory import DiffModelFactory, DiffListViewFactory
from dolt.models import Commit
from dolt.utils import db_for_commit
from dolt.functions import JSONObject

from . import diff_table_for_model, register_diff_tables


def three_dot_diffs(from_commit=None, to_commit=None):
    """three_dot_diffs returns a diff between the ancestor of from_to_commit with to_commit."""
    if not (from_commit and to_commit):
        raise ValueError("must specify both a to_commit and from_commit")
    merge_base = Commit.merge_base(from_commit, to_commit)
    return two_dot_diffs(from_commit=merge_base, to_commit=to_commit)


def two_dot_diffs(from_commit=None, to_commit=None):
    """two_dot_diffs returns the diff between from_commit and to_commit via the dolt diff table interface."""
    if not (from_commit and to_commit):
        raise ValueError("must specify both a to_commit and from_commit")

    diff_results = []
    for content_type in content_types_with_diffs(from_commit=from_commit, to_commit=to_commit):

        factory = DiffModelFactory(content_type)
        diffs = factory.get_model().objects.filter(from_commit=from_commit, to_commit=to_commit)
        to_queryset = (
            content_type.model_class()
            .objects.filter(pk__in=diffs.values_list("to_id", flat=True))
            .annotate(
                diff=Subquery(
                    diffs.annotate(
                        obj=JSONObject(
                            root=Value("to", output_field=models.CharField()),
                            **diff_annotation_query_fields(diffs.model),
                        )
                    )
                    .filter(to_id=OuterRef("id"))
                    .values("obj"),
                    output_field=models.JSONField(),
                ),
            )
            .using(db_for_commit(to_commit))
        )

        from_queryset = (
            content_type.model_class()
            .objects.filter(
                # we only want deleted rows in this queryset
                # modified rows come from `to_queryset`
                pk__in=diffs.filter(diff_type="removed").values_list("from_id", flat=True)
            )
            .annotate(
                diff=Subquery(
                    diffs.annotate(
                        obj=JSONObject(
                            root=Value("from", output_field=models.CharField()),
                            **diff_annotation_query_fields(diffs.model),
                        )
                    )
                    .filter(from_id=OuterRef("id"))
                    .values("obj"),
                    output_field=models.JSONField(),
                ),
            )
            # "time-travel" query the database at `from_commit`
            .using(db_for_commit(from_commit))
        )

        diff_rows = sorted(list(to_queryset) + list(from_queryset), key=lambda d: d.pk)
        if len(diff_rows) == 0:
            continue

        diff_view_table = DiffListViewFactory(content_type).get_table_model()
        diff_results.append(
            {
                "name": f"{factory.source_model_verbose_name} Diffs",
                "table": diff_view_table(diff_rows),
                "added": diffs.filter(diff_type="added").count(),
                "modified": diffs.filter(diff_type="modified").count(),
                "removed": diffs.filter(diff_type="removed").count(),
            }
        )
    return diff_results


def content_types_with_diffs(from_commit=None, to_commit=None):
    """
    Returns ContentType for models with non-empty diffs.
    """
    diff_counts = []
    for ct in ContentType.objects.all():
        model = ct.model_class()
        if not model or not diff_table_for_model(model):
            # only diff models that have registered a diff table
            continue
        diff_counts.append(
            f"""SELECT '{ct.app_label}', '{ct.model}', count(*) 
                FROM dolt_commit_diff_{model._meta.db_table}
                WHERE from_commit = '{from_commit}' 
                AND to_commit = '{to_commit}'"""
        )

    # UNION all the queries into one
    union = "(" + ") UNION (".join(diff_counts) + ")"

    with connection.cursor() as cursor:
        cursor.execute(union)
        res = cursor.fetchall()

    nonempty = filter(lambda tup: tup[2] != 0, res)
    return ContentType.objects.filter(
        app_label__in={tup[0] for tup in nonempty},
        model__in={tup[1] for tup in nonempty},
    )


def diff_annotation_query_fields(model):
    """diff_annotation_query_fields returns all of the column names for a model and turns them into to_ and from_ fields."""
    names = [
        f.name
        for f in model._meta.get_fields()
        # field names containing "__" cannot be
        # diffed as Django interprets kwargs with
        # "__" as lookups
        if "__" not in f.name
    ]
    return {name: F(name) for name in names}


register_diff_tables(
    {
        "dcim": {
            # "baseinterface": devices.BaseInterfaceTable,
            "cable": cables.CableTable,
            # "cabletermination": devices.CableTerminationTable,
            # "componenttemplate": devicetypes.ComponentTemplateTable,
            "consoleport": devices.ConsolePortTable,
            "consoleporttemplate": devicetypes.ConsolePortTemplateTable,
            "consoleserverport": devices.ConsoleServerPortTable,
            "consoleserverporttemplate": devicetypes.ConsoleServerPortTemplateTable,
            "device": devices.DeviceTable,
            "devicebay": devices.DeviceBayTable,
            "devicebaytemplate": devicetypes.DeviceBayTemplateTable,
            # "devicecomponent": devices.DeviceComponentTable,
            # "deviceconsoleport": devices.DeviceConsolePortTable,
            # "deviceconsoleserverport": devices.DeviceConsoleServerPortTable,
            # "devicedevicebay": devices.DeviceDeviceBayTable,
            # "devicefrontport": devices.DeviceFrontPortTable,
            # "deviceimport": devices.DeviceImportTable,
            # "deviceinterface": devices.DeviceInterfaceTable,
            # "deviceinventoryitem": devices.DeviceInventoryItemTable,
            # "devicepoweroutlet": devices.DevicePowerOutletTable,
            # "devicepowerport": devices.DevicePowerPortTable,
            # "devicerearport": devices.DeviceRearPortTable,
            "devicerole": devices.DeviceRoleTable,
            "devicetype": devicetypes.DeviceTypeTable,
            "frontport": devices.FrontPortTable,
            "frontporttemplate": devicetypes.FrontPortTemplateTable,
            "interface": devices.InterfaceTable,
            "interfacetemplate": devicetypes.InterfaceTemplateTable,
            "inventoryitem": devices.InventoryItemTable,
            "manufacturer": devicetypes.ManufacturerTable,
            # "pathendpoint": devices.PathEndpointTable,
            "platform": devices.PlatformTable,
            "powerfeed": power.PowerFeedTable,
            "poweroutlet": devices.PowerOutletTable,
            "poweroutlettemplate": devicetypes.PowerOutletTemplateTable,
            "powerpanel": power.PowerPanelTable,
            "powerport": devices.PowerPortTable,
            "powerporttemplate": devicetypes.PowerPortTemplateTable,
            "rack": racks.RackTable,
            # "rackdetail": racks.RackDetailTable,
            "rackgroup": racks.RackGroupTable,
            "rackreservation": racks.RackReservationTable,
            "rackrole": racks.RackRoleTable,
            "rearport": devices.RearPortTable,
            "rearporttemplate": devicetypes.RearPortTemplateTable,
            "region": sites.RegionTable,
            "site": sites.SiteTable,
            "virtualchassis": devices.VirtualChassisTable,
        },
        "circuits": {
            "circuit": circuits_tables.CircuitTable,
            # "circuittermination": None,
            "circuittype": circuits_tables.CircuitTypeTable,
            "provider": circuits_tables.ProviderTable,
        },
        "ipam": {
            "aggregate": ipam_tables.AggregateTable,
            "ipaddress": ipam_tables.IPAddressTable,
            "prefix": ipam_tables.PrefixTable,
            "rir": ipam_tables.RIRTable,
            "role": ipam_tables.RoleTable,
            "routetarget": ipam_tables.RouteTargetTable,
            "service": ipam_tables.ServiceTable,
            "vlan": ipam_tables.VLANTable,
            "vlangroup": ipam_tables.VLANGroupTable,
            "vrf": ipam_tables.VRFTable,
        },
        "tenancy": {
            "tenantgroup": tenancy_tables.TenantGroupTable,
            "tenant": tenancy_tables.TenantTable,
        },
        "virtualization": {
            "cluster": virtualization_tables.ClusterTypeTable,
            "clustergroup": virtualization_tables.ClusterGroupTable,
            "clustertype": virtualization_tables.ClusterTable,
            "vminterface": virtualization_tables.VMInterfaceTable,
        },
    }
)
