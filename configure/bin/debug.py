#!/usr/bin/env python
from django.core.management import setup_environ
import settings
setup_environ(settings)

from monitor.models import *
from configure.models import *
from configure.lib.state_manager import StateManager

from collections_24 import defaultdict
import sys

import cmd

class HydraDebug(cmd.Cmd, object):
    def __init__(self):
        super(HydraDebug, self).__init__()
        self.prompt = "Hydra> "

    def do_EOF(self, line):
        raise KeyboardInterrupt()

    def _create_target_mounts(self, node, target, failover_host):
        ManagedTargetMount.objects.get_or_create(
            block_device = node,
            target = target,
            host = node.host, 
            mount_point = target.default_mount_path(node.host),
            primary = True)

        if failover_host:
            if node.lun:
                try:
                    failover_node = LunNode.objects.get(host = failover_host, lun = node.lun)
                except LunNode.DoesNotExist:
                    failover_node = None
            else:
                failover_node = None
            # NB have to do this the long way because get_or_create will do the wrong thing on block_device=None 
            try:
                tm = ManagedTargetMount.objects.get(
                    target = target,
                    host = failover_host, 
                    mount_point = target.default_mount_path(failover_host),
                    primary = False)
            except ManagedTargetMount.DoesNotExist:
                tm = ManagedTargetMount(
                    block_device = failover_node,
                    target = target,
                    host = failover_host, 
                    mount_point = target.default_mount_path(failover_host),
                    primary = False)
                tm.save()

    def _load_target_config(self, info):
        host = Host.objects.get(address = info['host'])
        try:
            failover_host = Host.objects.get(address = info['failover_host'])
        except KeyError:
            failover_host = None
        node, created = LunNode.objects.get_or_create(host = host, path = info['device_node'])

        return node, host, failover_host

    from django.db import transaction
    @transaction.commit_on_success
    def do_load_config(self, config_file):
        import json
        text = open(config_file).read()
        data = json.loads(text)

        # FIXME: we rely on the good faith of the .json file's author to use
        # our canonical names for devices.  We must normalize them to avoid
        # the risk of double-using a LUN.

        for host_info in data['hosts']:
            host, created = ManagedHost.objects.get_or_create(address = host_info['address'])
            if created:
                host, ssh_monitor = SshMonitor.from_string(host_info['address'])
                host.save()
                ssh_monitor.host = host
                ssh_monitor.save()

        for mgs_info in data['mgss']:
            node, host, failover_host = self._load_target_config(mgs_info)

            try:
                mgs = ManagedMgs.objects.get(targetmount__host = host)
            except ManagedMgs.DoesNotExist:
                mgs = ManagedMgs(name = "MGS")
                mgs.save()

            self._create_target_mounts(node, mgs, failover_host)

        for filesystem_info in data['filesystems']:
            fs_mgs_host = Host.objects.get(address = filesystem_info['mgs'])
            mgs = ManagedMgs.objects.get(targetmount__host = fs_mgs_host)
            filesystem, created = ManagedFilesystem.objects.get_or_create(name = filesystem_info['name'], mgs = mgs)

            mds_info = filesystem_info['mds']
            mdt_node, mdt_host, mdt_failover_host = self._load_target_config(mds_info)
            try:
                mdt = ManagedMdt.objects.get(targetmount__block_device = mdt_node)
            except ManagedMdt.DoesNotExist:
                mdt = ManagedMdt(filesystem = filesystem)
                mdt.save()

            self._create_target_mounts(mdt_node, mdt, mdt_failover_host)

            for oss_info in filesystem_info['osss']:
                for device_node in oss_info['device_nodes']:
                    tmp_oss_info = oss_info
                    oss_info['device_node'] = device_node
                    node, host, failover_host = self._load_target_config(tmp_oss_info)

                    try:
                        oss = ManagedOst.objects.get(targetmount__block_device = node)
                    except ManagedOst.DoesNotExist:
                        oss = ManagedOst(filesystem = filesystem)
                        oss.save()

                        self._create_target_mounts(node, oss, failover_host)

    def do_format_fs(self, fs_name):
        fs = ManagedFilesystem.objects.get(name = fs_name)
        for target in fs.get_targets():
            if target.state == 'unformatted':
                StateManager.set_state(target, 'formatted')

    def do_start_fs(self, fs_name):
        fs = ManagedFilesystem.objects.get(name = fs_name)
        for target in fs.get_targets():
            StateManager.set_state(target.targetmount_set.get(primary = True).downcast(), 'mounted')

    def do_stop_fs(self, fs_name):
        fs = ManagedFilesystem.objects.get(name = fs_name)
        for target in fs.get_targets():
            if not target.state == 'unmounted':
                StateManager.set_state(target.targetmount_set.get(primary = True).downcast(), 'unmounted')

    def do_lnet_up(self, args):
        for host in ManagedHost.objects.all():
            StateManager.set_state(host, 'lnet_up')
    def do_lnet_down(self, args):
        for host in ManagedHost.objects.all():
            StateManager.set_state(host, 'lnet_down')

    def do_lnet_unload(self, args):
        for host in ManagedHost.objects.all():
            StateManager.set_state(host, 'lnet_unloaded')

    def do_poke_queue(self, args):
        from configure.models import Job
        Job.run_next()

    def do_apply_conf_param(self, args):
        from configure.models import ManagedMgs, ApplyConfParams
        job = ApplyConfParams(mgs = ManagedMgs.objects.get())
        from configure.lib.state_manager import StateManager
        StateManager().add_job(job)

    def _conf_param_test_instance(self, key, val, klass):
        if klass == MdtConfParam:
            try:
                mdt = ManagedMdt.objects.latest('id')
                return MdtConfParam(mdt = mdt, key = key, value = val)
            except ManagedMdt.DoesNotExist:
                return None
        elif klass == OstConfParam:
            try:
                ost = ManagedOst.objects.latest('id')
                return OstConfParam(ost = ost, key = key, value = val)
            except ManagedOst.DoesNotExist:
                return None
        elif klass in [FilesystemClientConfParam, FilesystemGlobalConfParam]:
            try:
                fs = ManagedFilesystem.objects.latest('id')
                return klass(filesystem = fs, key = key, value = val)
            except ManagedFilesystem.DoesNotExist:
                return None
        else:
            raise NotImplementedError()
    
    def do_test_conf_param(self, args):
        from configure.lib.conf_param import all_params
        from sys import stderr, stdout
        stdout.write("#!/bin/bash\n")
        stdout.write("set -e\n")
        for p,(param_obj_klass, param_validator, help_text) in all_params.items():
            for test_val in param_validator.test_vals():
                instance = self._conf_param_test_instance(p, test_val, param_obj_klass)
                if not instance:
                    stderr.write("Cannot create test instance for %s\n" % p)
                else:
                    stdout.write("echo lctl conf_param %s=%s\n" % (instance.get_key(), test_val))
                    stdout.write("lctl conf_param %s=%s\n" % (instance.get_key(), test_val))

if __name__ == '__main__':
    cmdline = HydraDebug

    if len(sys.argv) == 1:
        try:
            cmdline().cmdloop()
        except KeyboardInterrupt:
            print "Exiting..."
    else:
        cmdline().onecmd(" ".join(sys.argv[1:]))

