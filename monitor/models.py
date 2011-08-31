
# ==============================
# Copyright 2011 Whamcloud, Inc.
# ==============================

from django.db import models
from polymorphic.models import DowncastMetaclass

from collections_24 import defaultdict

import simplejson as json

from logging import INFO, WARNING

class Host(models.Model):
    __metaclass__ = DowncastMetaclass
    # FIXME: either need to make address non-unique, or need to
    # associate objects with a child object, because there
    # can be multiple servers on one hostname, eg ddn10ke
    address = models.CharField(max_length = 256)

    def __str__(self):
        return self.pretty_name()

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        MIN_LENGTH = 1
        if len(self.address) < MIN_LENGTH:
            raise ValidationError("Address '%s' is too short" % self.address)
        super(Host, self).save(*args, **kwargs)

    def pretty_name(self):
        if self.address[-12:] == ".localdomain":
            return self.address[:-12]
        else:
            return self.address
    
    def _role_strings(self):
        roles = set()
        for mountable in self.mountable_set.all():
            if isinstance(mountable, TargetMount):
                target = mountable.target.downcast()
                if mountable.primary:
                    if isinstance(target, ManagementTarget):
                        roles.add("MGS")
                    elif isinstance(target, MetadataTarget):
                        roles.add("MDS")
                    elif isinstance(target, ObjectStoreTarget):
                        roles.add("OSS")
                else:
                    roles.add("Failover")


            if isinstance(mountable, Client):
                roles.add("Client")

        if self.router_set.count() > 0:
            roles.add("Router")

        return roles

    def is_unused(self):
        return (len(self._role_strings()) == 0)

    def is_mgs(self):
        try:
            ManagementTarget.objects.get(targetmount__host = self)
            return True
        except ManagementTarget.DoesNotExist:
            return False

    def available_lun_nodes(self):
        from django.db.models import Q
        return LunNode.objects.filter(
                ~Q(lun__lunnode__used_hint = True),
                targetmount = None,
                host = self,
                used_hint = False)

    def role(self):
        roles = self._role_strings()
        if len(roles) == 0:
            return "Unused"
        else:
            return "/".join(roles)

    def status_string(self, targetmount_statuses = None):
        if targetmount_statuses == None:
            targetmount_statuses = dict([(tm, tm.status_string()) for tm in self.mountable_set.all() if isinstance(tm, TargetMount)])

        tm_states = set(targetmount_statuses.values())

        alerts = AlertState.filter_by_item(self)
        alert_klasses = [a.__class__ for a in alerts]
        if HostContactAlert in alert_klasses:
            return "OFFLINE"
        elif LNetOfflineAlert in alert_klasses or not (set(["STARTED", "SPARE"]) >= tm_states):
            return "WARNING"
        else:
            return "OK"

class Lun(models.Model):
    # The WWN from a device, available for some hardware
    # Support not yet implemented in lustre_audit
    #wwn = models.CharField(max_length = 16, blank = True, null = True)
    # The UUID from a filesystem on this Lun, available after formatting
    fs_uuid = models.CharField(max_length = 36, blank = True, null = True, unique = True)

    def __str__(self):
        return "Lun:%s" % self.fs_uuid

class LunNode(models.Model):
    lun = models.ForeignKey(Lun, blank = True, null = True)
    host = models.ForeignKey(Host)
    path = models.CharField(max_length = 512)

    # Size may be null for LunNodes created when setting up 
    # from a JSON file which just tells us a path.
    size = models.BigIntegerField(blank = True, null = True)

    used_hint = models.BooleanField()

    class Meta:
        unique_together = ('host', 'path')

    def __str__(self):
        return "%s:%s" % (self.host, self.path)

    def pretty_string(self):
        if self.path.startswith('/dev/disk/by-path/'):
            short_name = self.path.replace('/dev/disk/by-path/', '', 1)

            # e.g. ip-192.168.122.1:3260-iscsi-iqn.2011-08.com.whamcloud.lab.hydra-1.sdb-lun-0
            if short_name.startswith("ip-") and short_name.index("-iscsi-") != -1:
                iscsi_iqn = "".join(short_name.split("-iscsi-")[1:])
                short_name = "iSCSI %s" % iscsi_iqn

            # e.g. /dev/disk/by-path/pci-0000:00:06.0-scsi-0:0:3:0    
            if short_name.startswith("pci-") and short_name.index("-scsi-") != -1:
                scsi_id = "".join(short_name.split("-scsi-")[1:])
                short_name = "SCSI %s" % scsi_id
        elif self.path.startswith('/dev/mapper/'):
            # e.g. /dev/mapper/VolGroup00-blob0
            short_name = self.path.replace('/dev/mapper/', '', 1)
            short_name = "LVM %s" % short_name
        elif self.path.startswith('/dev/'):
            # e.g. /dev/sda
            short_name = self.path.replace('/dev/', '', 1)
        else:
            short_name = self.path

        def sizeof_fmt(num):
            # http://stackoverflow.com/questions/1094841/reusable-library-to-get-human-readable-version-of-file-size/1094933#1094933
            for x in ['bytes','KB','MB','GB','TB', 'EB', 'ZB', 'YB']:
                if num < 1024.0:
                    return "%3.1f%s" % (num, x)
                num /= 1024.0

        human_size = sizeof_fmt(self.size)

        return "%s (%s)" % (short_name, human_size)

class Monitor(models.Model):
    __metaclass__ = DowncastMetaclass

    host = models.OneToOneField(Host)

    #idle, tasking, tasked, started, 
    state = models.CharField(max_length = 32, default = 'idle')
    task_id = models.CharField(max_length=36, blank = True, null = True, default = None)
    counter = models.IntegerField(default = 0)

    from django.db import transaction
    @transaction.commit_on_success
    def update(self, **kwargs):
        for k,v in kwargs.items():
            setattr(self, k, v)
        self.save()

    def try_schedule(self):
        """Return True if a run was scheduled, else False"""
        from monitor.tasks import monitor_exec
        from monitor.lib.lustre_audit import audit_log

        if self.state == 'tasking':
            audit_log.warn("Monitor %d found in state 'tasking' (crash recovery).  Going to idle." % self.id)
            self.update(state = 'idle')

        if self.state == 'idle':
            self.update(state = 'tasking', counter = self.counter + 1)
            celery_task = monitor_exec.delay(self.id, self.counter)
            self.update(state = 'tasked', task_id = celery_task.task_id)

            return True
        else:
            return False

    def invoke(self):
        """Subclasses implement this, return a dict"""
        raise NotImplementedError

class SshMonitor(Monitor):
    DEFAULT_AGENT_PATH = '/usr/bin/hydra-agent.py'
    DEFAULT_USERNAME = 'root'

    # Substituted with DEFAULT_USERNAME in get_username if None
    username = models.CharField(max_length = 64, blank = True, null = True)
    # Substituted with DEFAULT_AGENT_PATH in get_agent_path if None
    agent_path = models.CharField(max_length = 512, blank = True, null = True)
    # Not passed on if None (let SSH library decide which port to use)
    port = models.IntegerField(blank = True, null = True)

    def invoke(self):
        """Safe to call on an SshMonitor which has a host assigned, neither
        need to have been saved"""

        import paramiko
        import socket
        ssh = paramiko.SSHClient()
        # TODO: manage host keys
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            from settings import AUDIT_PERIOD
            # How long it may take to establish a TCP connection
            SOCKET_TIMEOUT = AUDIT_PERIOD
            # How long it may take to get the output of our agent
            # (including tunefs'ing N devices)
            SSH_READ_TIMEOUT = AUDIT_PERIOD

            args = {"hostname": self.host.address,
                    "username": self.get_username(),
                    "timeout": SOCKET_TIMEOUT}
            if self.port:
                args["port"] = self.port
            # Note: paramiko has a hardcoded 15 second timeout on SSH handshake after
            # successful TCP connection (Transport.banner_timeout).
            ssh.connect(**args)
            transport = ssh.get_transport()
            channel = transport.open_session()
            channel.settimeout(SSH_READ_TIMEOUT)
            channel.exec_command(self.get_agent_path())
            result = channel.makefile('rb').read()
            ssh.close()
        except socket.timeout,e:
            return e
        except socket.error,e:
            return e
        except paramiko.SSHException,e:
            return e

        try:
            return json.loads(result)
        except Exception, e:
            return e

    def get_agent_path(self):
        if self.agent_path:
            return self.agent_path
        else:
            return SshMonitor.DEFAULT_AGENT_PATH

    def get_username(self):
        if self.username:
            return self.username
        else:
            return SshMonitor.DEFAULT_USERNAME

    @staticmethod
    def from_string(address, agent_path = None):
        """Return an unsaved SshMonitor instance, with the Host either set to 
           an existing Host with the right address, or a new unsaved Host."""
        if address.find("@") != -1:
            user,host = address.split("@")
        else:
            user = None
            host = address

        if host.find(":") != -1:
            host, port = host.split(":")
        else:
            port = None

        try:
            from configure.models import ManagedHost
            host_klass = ManagedHost
        except ImportError:
            host_klass = Host

        agent_path = SshMonitor.DEFAULT_AGENT_PATH
        try:
            host = host_klass.objects.get(address = host)
        except host_klass.DoesNotExist:
            host = host_klass(address = host)

        try:
            return host, SshMonitor.objects.get(
                    host = host,
                    username = user,
                    port = port,
                    agent_path = agent_path)
        except SshMonitor.DoesNotExist:
            return host, SshMonitor(
                    host = host,
                    username = user,
                    port = port,
                    agent_path = agent_path)

    def ssh_address_str(self):
        return "%s@%s" % (self.get_username(), self.host.address.__str__())

class Nid(models.Model):
    """Simplified NID representation for monitoring only"""
    host = models.ForeignKey(Host)
    nid_string = models.CharField(max_length=128)

class Router(models.Model):
    host = models.ForeignKey(Host)

class Filesystem(models.Model):
    name = models.CharField(max_length=8)
    mgs = models.ForeignKey('ManagementTarget')

    class Meta:
        unique_together = ('name', 'mgs')

    def get_targets(self):
        return [self.mgs.downcast()] + self.get_filesystem_targets()

    def get_filesystem_targets(self):
        osts = list(ObjectStoreTarget.objects.filter(filesystem = self).all())
        # NB using __str__ instead of name because name may not 
        # be set in all cases
        osts.sort(lambda i,j: cmp(i.__str__()[-4:], j.__str__()[-4:]))

        return list(MetadataTarget.objects.filter(filesystem = self).all()) + osts

    def get_servers(self):
        targets = self.get_targets()
        servers = defaultdict(list)
        for t in targets:
            for tm in t.targetmount_set.all():
                servers[tm.host].append(tm)

        # NB converting to dict because django templates don't place nice with defaultdict
        # (http://stackoverflow.com/questions/4764110/django-template-cant-loop-defaultdict)
        return dict(servers)

    def status_string(self, target_statuses = None):
        if target_statuses == None:
            target_statuses = dict([(t, t.status_string()) for t in self.get_targets()])

        filesystem_targets_statuses = [v for k,v in target_statuses.items() if not k.__class__ == ManagementTarget]
        all_statuses = target_statuses.values()

        good_status = set(["STARTED", "FAILOVER"])
        # If all my targets are down, I'm red, even if my MGS is up
        if not good_status & set(filesystem_targets_statuses):
            return "OFFLINE"

        # If all my targets are up including the MGS, then I'm green
        if set(all_statuses) <= set(["STARTED"]):
            return "OK"

        # Else I'm orange
        return "WARNING"

    # FIXME: should this be defined in the ManagementTarget class?
    def mgs_nids(self):
        """Return a list of mgs nid strings"""
        nids = []
        mgs = self.mgs
        for target_mount in mgs.targetmount_set.all():
            host = target_mount.host
            nids.extend([n.nid_string for n in host.nid_set.all()])

        return nids

    def mgsnode_spec(self):
        """Return a list of strings of --mgsnode arguments suitable for use with mkfs"""
        result = []

        nids = ",".join(self.mgs_nids())
        assert(nids != "")
        result.append("--mgsnode=%s" % nids)

        return result

    def mgs_spec(self):
        """Return a string which is foo in <foo>:/lustre for client mounts"""
        mgs = self.mgs
        nid_specs = []
        for target_mount in mgs.targetmount_set.all():
            host = target_mount.host
            nids = ",".join([n.nid_string for n in host.nid_set.all()])
            if nids == "":
                raise ValueError("NIDs for MGS host %s not known" % host)

            nid_specs.append(nids)
            
        return ":".join(nid_specs)

    def mount_example(self):
        try:
            return "mount -t lustre %s:/%s /mnt/client" % (self.mgs_spec(), self.name)
        except ValueError,e:
            return "Not ready to mount: %s" % e

    def __str__(self):
        return self.name

class Mountable(models.Model):
    """Something that can be mounted on a particular host (roughly
       speaking a line in fstab."""
    __metaclass__ = DowncastMetaclass
    host = models.ForeignKey('Host')
    mount_point = models.CharField(max_length = 512, null = True, blank = True)

    def device(self):
        """To be implemented by child classes"""
        raise NotImplementedError()

    def role(self):
        """To be implemented by child classes"""
        raise NotImplementedError()

    def status_string(self):
        """To be implemented by child classes"""
        raise NotImplementedError()

class FilesystemMember(models.Model):
    """A Mountable for a particular filesystem, such as 
       MDT, OST or Client"""
    filesystem = models.ForeignKey(Filesystem)
    # uSE OF ABSTRACT BASE CLASSES TO AVOID DJANGO BUG #12002
    class Meta:
        abstract = True

class TargetMount(Mountable):
    """A mountable (host+mount point+device()) which associates a Target
       with a particular location to mount as primary or as failover"""
    block_device = models.ForeignKey(LunNode, blank = True, null = True)
    primary = models.BooleanField()
    target = models.ForeignKey('Target')
    # FIXME: duplication of host reference from Mountable and LunNode

    def save(self, force_insert = False, force_update = False, using = None):
        # If primary is true, then target must be unique
        if self.primary:
            from django.db.models import Q
            other_primaries = TargetMount.objects.filter(~Q(id = self.id), target = self.target, primary = True)
            if other_primaries.count() > 0:
                from django.core.exceptions import ValidationError
                raise ValidationError("Cannot have multiple primary mounts for target %s" % self.target)


        # If this is an MGS, there may not be another MGS on 
        # this host
        try:
            from django.db.models import Q
            mgs = self.target.managementtarget
            other_mgs_mountables_local = TargetMount.objects.filter(~Q(target__managementtarget = None), ~Q(id = self.id), host = self.host).count()
            if other_mgs_mountables_local > 0:
                from django.core.exceptions import ValidationError
                raise ValidationError("Cannot have multiple MGS mounts on host %s" % self.host.address)

        except ManagementTarget.DoesNotExist:
            pass

        return super(TargetMount, self).save(force_insert, force_update, using)

    def __str__(self):
        return "%s" % (self.target)

    def device(self):
        return self.block_device.path

    def status_string(self):
        # Look for alerts that can affect this item:
        # statuses are STARTED STOPPED RECOVERY
        alerts = AlertState.filter_by_item(self)
        alert_klasses = [a.__class__ for a in alerts]
        if len(alerts) == 0:
            if self.primary:
                return "STARTED"
            else:
                return "SPARE"
        if TargetRecoveryAlert in alert_klasses:
            return "RECOVERY"
        if MountableOfflineAlert in alert_klasses:
            return "STOPPED"
        if FailoverActiveAlert in alert_klasses:
            return "FAILOVER"
        raise NotImplementedError("Unhandled target alert %s" % alert_klasses)

    def pretty_block_device(self):
        # Truncate to iSCSI iqn if possible
        parts = self.block_device.path.split("-iscsi-")
        if len(parts) == 2:
            return parts[1]
        
        # Strip /dev/mapper if possible
        parts = self.block_device.path.split("/dev/mapper/")
        if len(parts) == 2:
            return parts[1]

        # Strip /dev if possible
        parts = self.block_device.path.split("/dev/")
        if len(parts) == 2:
            return parts[1]

        # Fall through, do nothing
        return self.block_device

class Target(models.Model):
    """A Lustre filesystem target (MGS, MDT, OST) in the abstract, which
       may be accessible through 1 or more hosts via TargetMount"""
    __metaclass__ = DowncastMetaclass
    # Like testfs-OST0001
    # Nullable because when manager creates a Target it doesn't know the name
    # until it's formatted+started+audited
    name = models.CharField(max_length = 64, null = True, blank = True)

    def name_no_fs(self):
        """Something like OST0001 rather than testfs1-OST0001"""
        if self.name:
            if self.name.find("-") != -1:
                return self.name.split("-")[1]
            else:
                return self.name
        else:
            return self.downcast().role()

    def primary_server(self):
        return self.targetmount_set.get(primary = True).host

    def failover_servers(self):
        return self.targetmount_set.get(primary = False).host

    def status_string(self, mount_statuses = None):
        if mount_statuses == None:
            mount_statuses = dict([(m, m.status_string()) for m in self.targetmount_set.all()])

        if "STARTED" in mount_statuses.values():
            return "STARTED"
        elif "RECOVERY" in mount_statuses.values():
            return "RECOVERY"
        elif "FAILOVER" in mount_statuses.values():
            return "FAILOVER"
        else:
            return "STOPPED"
        # TODO: give statuses that reflect primary/secondaryness for FAILOVER

    def get_param(self, key):
        params = self.targetparam_set.filter(key = key)
        return [p.value for p in params]

    def get_params(self):
        return [(p.key,p.value) for p in self.targetparam_set.all()]

    def primary_host(self):
        return TargetMount.objects.get(target = self, primary = True).host

    def __str__(self):
        if self.name:
            return self.name
        else:
            return "Unregistered %s %s" % (self.downcast().role(), self.id)

class MetadataTarget(Target, FilesystemMember):
    # TODO: constraint to allow only one MetadataTarget per MGS.  The reason
    # we don't just use a OneToOneField is to use FilesystemMember to represent
    # MDTs and OSTs together in a convenient way
    def __str__(self):
        if not self.name:
            return "Unregistered %s-MDT" % (self.filesystem.name)
        else:
            return self.name

    def role(self):
        return "MDT"

class ManagementTarget(Target):
    def role(self):
        return "MGS"

    @staticmethod
    def get_by_host(host):
        return ManagementTarget.objects.get(targetmount__host = host)

    
class ObjectStoreTarget(Target, FilesystemMember):
    def __str__(self):
        if not self.name:
            return "Unregistered %s-OST" % (self.filesystem.name)
        else:
            return self.name

    def role(self):
        return "OST"

class Client(Mountable, FilesystemMember):
    def role(self):
        return "Client"

    def status_string(self):
        # Look for alerts that can affect this item:
        # statuses are STARTED STOPPED
        alerts = AlertState.filter_by_item(self)
        alert_klasses = [a.__class__ for a in alerts]
        if len(alerts) == 0:
            return "STARTED"
        if MountableOfflineAlert in alert_klasses:
            return "STOPPED"
        raise NotImplementedError("Unhandled target alert %s" % alert_klasses)

    def __str__(self):
        return "%s-client %d" % (self.filesystem.name, self.id)


class Event(models.Model):
    __metaclass__ = DowncastMetaclass

    created_at = models.DateTimeField(auto_now_add = True)
    severity = models.IntegerField()
    host = models.ForeignKey(Host, blank = True, null = True)

    @staticmethod
    def type_name():
        raise NotImplementedError

    def severity_class(self):
        # CSS class from an Event severity -- FIXME: this should be a templatetag
        from logging import INFO, WARNING, ERROR
        try:
            return {INFO: 'info', WARNING: 'warning', ERROR: 'error'}[self.severity]
        except KeyError:
            return ""

    def message(self):
        raise NotImplementedError

from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.generic import GenericForeignKey
class LearnEvent(Event):
    # Every environment at some point reinvents void* :-)
    learned_item_type = models.ForeignKey(ContentType)
    learned_item_id = models.PositiveIntegerField()
    learned_item = GenericForeignKey('learned_item_type', 'learned_item_id')

    @staticmethod
    def type_name():
        return "Autodetection"

    def message(self):
        if isinstance(self.learned_item, TargetMount):
            return "Discovered mount point of %s on %s" % (self.learned_item, self.learned_item.host)
        elif isinstance(self.learned_item, Target):
            return "Discovered formatted target %s" % (self.learned_item)
        elif isinstance(self.learned_item, Filesystem):
            return "Discovered filesystem %s on MGS %s" % (self.learned_item, self.learned_item.mgs.targetmount_set.get(primary = True).host)
        else:
            return "Discovered %s" % self.learned_item

class AlertEvent(Event):
    message_str = models.CharField(max_length = 512)
    alert = models.ForeignKey('AlertState')

    @staticmethod
    def type_name():
        return "Alert"

    def message(self):
        return self.message_str

class AlertState(models.Model):
    """Records a period of time during which a particular
       issue affected a particular element of the system"""
    __metaclass__ = DowncastMetaclass

    alert_item_type = models.ForeignKey(ContentType, related_name='alertstate_alert_item_type')
    alert_item_id = models.PositiveIntegerField()
    # FIXME: generic foreign key does not automatically set up deletion
    # of this when the alert_item is deleted -- do it manually
    alert_item = GenericForeignKey('alert_item_type', 'alert_item_id')

    begin = models.DateTimeField()
    end = models.DateTimeField()
    active = models.BooleanField()

    def duration(self):
        return self.end - self.begin

    @classmethod
    def filter_by_item(cls, item):
        if hasattr(item, 'content_type'):
            # A DowncastMetaclass object
            return cls.objects.filter(active = True, 
                    alert_item_id = item.id,
                    alert_item_type = item.content_type)
        else:
            return cls.objects.filter(active = True, 
                    alert_item_id = item.id,
                    alert_item_type__model = item.__class__.__name__.lower(),
                    alert_item_type__app_label = item.__class__._meta.app_label)

    @classmethod
    def notify(alert_klass, alert_item, active):
        alert_item = alert_item.downcast()

        if active:
            alert_klass.high(alert_item)
        else:
            alert_klass.low(alert_item)

    @classmethod
    def high(alert_klass, alert_item):
        import datetime
        now = datetime.datetime.now()
        try:
            alert_state = alert_klass.filter_by_item(alert_item).get()
            alert_state.end = now
            alert_state.save()
        except alert_klass.DoesNotExist:
            alert_state = alert_klass(
                    active = True,
                    begin = now,
                    end = now,
                    alert_item = alert_item)
            alert_state.save()
            alert_state.begin_event().save()

        return alert_state

    @classmethod
    def low(alert_klass, alert_item):
        import datetime
        now = datetime.datetime.now()
        try:
            alert_state = alert_klass.filter_by_item(alert_item).get()
            alert_state.end = now
            alert_state.active = False
            alert_state.save()
            alert_state.end_event().save()
        except alert_klass.DoesNotExist:
            alert_state = None

        return alert_state

class MountableOfflineAlert(AlertState):
    def message(self):
        if isinstance(self.alert_item, TargetMount):
            return "Target offline"
        elif isinstance(self.alert_item, Client):
            return "Client offline"
        else:
            raise NotImplementedError

    def begin_event(self):
        return AlertEvent(
                message_str = "%s stopped" % self.alert_item,
                host = self.alert_item.host,
                alert = self,
                severity = WARNING)
        
    def end_event(self):
        return AlertEvent(
                message_str = "%s started" % self.alert_item,
                host = self.alert_item.host,
                alert = self,
                severity = INFO)

class FailoverActiveAlert(AlertState):
    def message(self):
        return "Failover active"

    def begin_event(self):
        return AlertEvent(
                message_str = "%s failover mounted" % self.alert_item,
                host = self.alert_item.host,
                alert = self,
                severity = WARNING)
        
    def end_event(self):
        return AlertEvent(
                message_str = "%s failover unmounted" % self.alert_item,
                host = self.alert_item.host,
                alert = self,
                severity = INFO)

class HostContactAlert(AlertState):
    def message(self):
        return "Host contact lost"

    def begin_event(self):
        return AlertEvent(
                message_str = "Lost contact with host %s" % self.alert_item,
                host = self.alert_item,
                alert = self,
                severity = WARNING)

    def end_event(self):
        return AlertEvent(
                message_str = "Re-established contact with host %s" % self.alert_item,
                host = self.alert_item,
                alert = self,
                severity = INFO)

class TargetRecoveryAlert(AlertState):
    def message(self):
        return "Target in recovery"

    def begin_event(self):
        return AlertEvent(
                message_str = "Target '%s' went into recovery" % self.alert_item,
                host = self.alert_item.host,
                alert = self,
                severity = WARNING)

    def end_event(self):
        return AlertEvent(
                message_str = "Target '%s' completed recovery" % self.alert_item,
                host = self.alert_item.host,
                alert = self,
                severity = INFO)

class LNetOfflineAlert(AlertState):
    def message(self):
        return "LNet offline"

    def begin_event(self):
        return AlertEvent(
                message_str = "LNet stopped on host '%s'" % self.alert_item,
                host = self.alert_item,
                alert = self,
                severity = WARNING)

    def end_event(self):
        return AlertEvent(
                message_str = "LNet started on host '%s'" % self.alert_item,
                host = self.alert_item,
                alert = self,
                severity = INFO)

class TargetParam(models.Model):
    target = models.ForeignKey(Target)
    key = models.CharField(max_length=128)
    value = models.CharField(max_length=512)

    @staticmethod
    def update_params(target, params):
        from monitor.lib.lustre_audit import audit_log

        old_params = set(target.get_params())

        new_params = set()
        for key, value_list in params.items():
            for value in value_list:
                new_params.add((key, value))
        
        for del_param in old_params - new_params:
            target.targetparam_set.get(key = del_param[0], value = del_param[1]).delete()
            audit_log.info("del_param: %s" % (del_param,))
        for add_param in new_params - old_params:
            target.targetparam_set.create(key = add_param[0], value = add_param[1])
            audit_log.info("add_param: %s" % (add_param,))

class TargetMountRecoveryInfo(models.Model):
    # When a volume is present, we will have been able to interrogate 
    # its recovery status
    # JSON-encoded dict parsed from /proc/fs/lustre/*/*/recovery_status
    recovery_status = models.TextField()

    target_mount = models.ForeignKey(TargetMount)

    from django.db import transaction
    @staticmethod
    @transaction.commit_on_success
    def update(target_mount, recovery_status):
        TargetMountRecoveryInfo.objects.filter(target_mount = target_mount).delete()
        instance = TargetMountRecoveryInfo.objects.create(
                target_mount = target_mount,
                recovery_status = json.dumps(recovery_status))
        return instance.is_recovering(recovery_status) 

    def is_recovering(self, data = None):
        if not data:
            data = json.loads(self.recovery_status)
        return (data.has_key("status") and data["status"] == "RECOVERING")

    def recovery_status_str(self):
        data = json.loads(self.recovery_status)
        if data.has_key("status") and data["status"] == "RECOVERING":
            return "%s %ss remaining" % (data["status"], data["time_remaining"])
        elif data.has_key("status"):
            return data["status"]
        else:
            return "N/A"

# Only do admin registration if we are not being imported
# by the configure app
#try:
#    CONFIGURE_MODELS
#except NameError:
#    from django.contrib import admin
#    admin.site.register(TargetParam)
#    admin.site.register(Client)
#    admin.site.register(Filesystem)
#    admin.site.register(Host)
#    admin.site.register(ManagementTarget)
#    admin.site.register(MetadataTarget)
#    admin.site.register(Mountable)
#    admin.site.register(Nid)
#    admin.site.register(ObjectStoreTarget)
#    admin.site.register(Router)
#    admin.site.register(Target)
#    admin.site.register(TargetMount)

#    admin.site.register(Event)
#    admin.site.register(LearnEvent)
#    admin.site.register(AlertEvent)

