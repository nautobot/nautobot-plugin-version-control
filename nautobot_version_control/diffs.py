"""Diffs.py contains a set of utilities for producing Dolt diffs."""

from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db import models
from django.db.models.expressions import RawSQL

from nautobot.circuits import tables as circuits_tables
from nautobot.dcim.tables import cables, devices, devicetypes, power, racks, sites
from nautobot.extras import tables as extras_tables
from nautobot.ipam import tables as ipam_tables
from nautobot.tenancy import tables as tenancy_tables
from nautobot.virtualization import tables as virtualization_tables

from nautobot_version_control.dynamic.diff_factory import DiffListViewFactory
from nautobot_version_control.models import Commit
from nautobot_version_control.utils import db_for_commit

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
    for content_type in ContentType.objects.all():
        model = content_type.model_class()
        if not model:
            continue
        if not diff_table_for_model(model):
            continue

        ct_meta = content_type.model_class()._meta
        tbl_name = ct_meta.db_table
        verbose_name = str(ct_meta.verbose_name.capitalize())

        to_queryset = (
            content_type.model_class()
            .objects.filter(
                pk__in=RawSQL(  # nosec
                    f"""SELECT to_id FROM dolt_commit_diff_{tbl_name}
                        WHERE to_commit = %s AND from_commit = %s""",
                    (to_commit, from_commit),
                )
            )
            .annotate(
                # Annotate each row with a JSON-ified diff
                diff=RawSQL(  # nosec
                    f"""SELECT JSON_OBJECT("root", "to", {json_diff_fields(tbl_name)})
                        FROM dolt_commit_diff_{tbl_name}
                        WHERE to_commit = %s AND from_commit = %s
                        AND to_id = {tbl_name}.id """,
                    (to_commit, from_commit),
                    output_field=models.JSONField(),
                )
            )
            # "time-travel" query the database at `to_commit`
            .using(db_for_commit(to_commit))
        )

        from_queryset = (
            content_type.model_class()
            .objects.filter(
                # add the `diff_type = 'removed'` clause, because we only want deleted
                # rows in this queryset. modified rows come from the `to_queryset`
                pk__in=RawSQL(  # nosec
                    f"""SELECT from_id FROM dolt_commit_diff_{tbl_name}
                        WHERE to_commit = %s AND from_commit = %s AND diff_type = 'removed' """,
                    (to_commit, from_commit),
                )
            )
            .annotate(
                # Annotate each row with a JSON-ified diff
                diff=RawSQL(  # nosec
                    f"""SELECT JSON_OBJECT("root", "from", {json_diff_fields(tbl_name)})
                        FROM dolt_commit_diff_{tbl_name}
                        WHERE to_commit = %s AND from_commit = %s
                        AND from_id = {tbl_name}.id """,
                    (to_commit, from_commit),
                    output_field=models.JSONField(),
                )
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
                "name": f"{verbose_name} Diffs",
                "table": diff_view_table(diff_rows),
                **diff_summary_for_table(tbl_name, from_commit, to_commit),
            }
        )
    return diff_results


def diff_summary_for_table(table, from_commit, to_commit):
    """diff_summary_for_table returns the diff summary for table, for the commits from_commit and to_commit."""
    summary = {
        "added": 0,
        "modified": 0,
        "removed": 0,
    }
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT diff_type, count(diff_type) FROM dolt_commit_diff_{table} "  # nosec
            + "WHERE to_commit = %s AND from_commit = %s"
            "GROUP BY diff_type ORDER BY diff_type",
            (to_commit, from_commit),
        )
        for diff_type, count in cursor.fetchall():
            summary[diff_type] = count
    return summary


def json_diff_fields(tbl_name):
    """
    json_diff_fields returns all of the column names for a model
    and turns them into to_ and from_ fields.
    """
    with connection.cursor() as cursor:
        cursor.execute(f"DESCRIBE dolt_commit_diff_{tbl_name}")
        cols = cursor.fetchall()
    pairs = (f"'{c[0]}', dolt_commit_diff_{tbl_name}.{c[0]}" for c in cols)
    return ", ".join(pairs)


register_diff_tables(
    {
        "circuits": {
            "circuit": circuits_tables.CircuitTable,
            # "circuittermination": None,
            "circuittype": circuits_tables.CircuitTypeTable,
            "provider": circuits_tables.ProviderTable,
        },
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
        "extras": {
            "secret": extras_tables.SecretTable,
            "secretsgroup": extras_tables.SecretsGroupTable,
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
