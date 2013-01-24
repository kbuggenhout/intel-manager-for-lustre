import logging
import re

from testconfig import config

from tests.integration.core.api_testcase import ApiTestCase
from tests.integration.core.constants import TEST_TIMEOUT

logger = logging.getLogger('test')
logger.setLevel(logging.DEBUG)


class CleanClusterApiTestCase(ApiTestCase):
    """
    Adds a few different ways of cleaning out a test cluster.
    """

    def reset_cluster(self):
        """
        Will fully wipe a test cluster:
          - dropping and recreating the chroma manager database
          - unmounting any lustre filesystems from the clients
          - unconfiguring any chroma targets in pacemaker
        """
        self.unmount_filesystems_from_clients()
        self.reset_chroma_manager_db()
        self.remove_all_targets_from_pacemaker()

    def reset_chroma_manager_db(self):
        for chroma_manager in config['chroma_managers']:
            superuser = [u for u in chroma_manager['users'] if u['super']][0]

            # Stop all chroma manager services
            result = self.remote_command(
                chroma_manager['address'],
                'chroma-config stop',
                expected_return_code = None
            )
            if not result.exit_status == 0:
                logger.warn("chroma-config stop failed: rc:%s out:'%s' err:'%s'" % (result.exit_status, result.stdout.read(), result.stderr.read()))

            # Wait for all of the chroma manager services to stop
            running_time = 0
            services = ['chroma-worker', 'chroma-storage', 'httpd']
            while services and running_time < TEST_TIMEOUT:
                for service in services:
                    result = self.remote_command(
                        chroma_manager['address'],
                        'service %s status' % service,
                        expected_return_code = None
                    )
                    if result.exit_status == 3:
                        services.remove(service)
                running_time += 1
            self.assertEqual(services, [], "Not all services were stopped by chroma-config before timeout: %s" % services)

            # Drop the database to start from a clean state.
            self.remote_command(
                chroma_manager['address'],
                'echo "drop database chroma; create database chroma;" | mysql -u root'
            )

            # Run chroma-config setup to recreate the database and start the chroma manager.
            result = self.remote_command(
                chroma_manager['address'],
                "chroma-config setup %s %s localhost &> config_setup.log" % (superuser['username'], superuser['password']),
                expected_return_code = None
            )
            chroma_config_exit_status = result.exit_status
            if not chroma_config_exit_status == 0:
                result = self.remote_command(
                    chroma_manager['address'],
                    "cat config_setup.log"
                )
                self.assertEqual(0, chroma_config_exit_status, "chroma-config setup failed: '%s'" % result.stdout.read())

    def has_pacemaker(self, server):
        result = self.remote_command(
            server['address'],
            'which crm',
            expected_return_code = None
        )
        return result.exit_status == 0

    def get_pacemaker_targets(self, server):
        """
        Returns a list of chroma targets configured in pacemaker on a server.
        """
        result = self.remote_command(
            server['address'],
            'crm resource list'
        )
        crm_resources = result.stdout.read().split('\n')
        return [r.split()[0] for r in crm_resources if re.search('chroma:Target', r)]

    def is_pacemaker_target_running(self, server, target):
        result = self.remote_command(
            server['address'],
            "crm resource status %s" % target
        )
        return re.search('is running', result.stdout.read())

    def remove_all_targets_from_pacemaker(self):
        """
        Stops and deletes all chroma targets for any corosync clusters
        configured on any of the lustre servers appearing in the cluster config
        """
        for server in config['lustre_servers']:
            if self.has_pacemaker(server):
                crm_targets = self.get_pacemaker_targets(server)

                # Stop targets and delete targets
                for target in crm_targets:
                    self.remote_command(server['address'], 'crm resource stop %s' % target)
                for target in crm_targets:
                    self.wait_until_true(lambda: not self.is_pacemaker_target_running(server, target))
                    self.remote_command(server['address'], 'crm configure delete %s' % target)
                    self.remote_command(server['address'], 'crm resource cleanup %s' % target)

                # Verify no more targets
                self.wait_until_true(lambda: not self.get_pacemaker_targets(server))

                # Remove chroma-agent's records of the targets
                self.remote_command(
                    server['address'],
                    'rm -rf /var/lib/chroma/*',
                    expected_return_code = None  # Keep going if it failed - may be none there.
                )
                self.remote_command(
                    server['address'],
                    'service chroma-agent restart'
                )

            else:
                logger.info("%s does not appear to have pacemaker - skipping any removal of targets." % server['address'])

    def unmount_filesystems_from_clients(self):
        """
        Unmount all filesystems of type lustre from all clients in the config.
        """
        for client in config['lustre_clients'].keys():
            self.remote_command(
                client,
                'umount -t lustre -a'
            )
            result = self.remote_command(
                client,
                'mount'
            )
            self.assertNotRegexpMatches(
                result.stdout.read(),
                " type lustre"
            )

    def graceful_teardown(self, chroma_manager):
        """
        Removes all filesystems, MGSs, and hosts from chroma via the api.
        """
        response = chroma_manager.get(
            '/api/filesystem/',
            params = {'limit': 0}
        )
        self.assertEqual(response.status_code, 200)
        filesystems = response.json['objects']

        if len(filesystems) > 0:
            # Unmount filesystems
            for client in config['lustre_clients'].keys():
                for filesystem in filesystems:
                    self.unmount_filesystem(client, filesystem['name'])

        if len(filesystems) > 0:
            # Remove filesystems
            remove_filesystem_command_ids = []
            for filesystem in filesystems:
                response = chroma_manager.delete(filesystem['resource_uri'])
                self.assertTrue(response.successful, response.text)
                command_id = response.json['command']['id']
                self.assertTrue(command_id)
                remove_filesystem_command_ids.append(command_id)

            self.wait_for_commands(chroma_manager, remove_filesystem_command_ids)

        # Remove MGT
        response = chroma_manager.get(
            '/api/target/',
            params = {'kind': 'MGT', 'limit': 0}
        )
        mgts = response.json['objects']

        if len(mgts) > 0:
            remove_mgt_command_ids = []
            for mgt in mgts:
                response = chroma_manager.delete(mgt['resource_uri'])
                command_id = response.json['command']['id']
                self.assertTrue(command_id)
                remove_mgt_command_ids.append(command_id)

            self.wait_for_commands(chroma_manager, remove_mgt_command_ids)

        # Remove hosts
        response = chroma_manager.get(
            '/api/host/',
            params = {'limit': 0}
        )
        self.assertTrue(response.successful, response.text)
        hosts = response.json['objects']

        if len(hosts) > 0:
            remove_host_command_ids = []
            for host in hosts:
                response = chroma_manager.delete(host['resource_uri'])
                self.assertTrue(response.successful, response.text)
                command_id = response.json['command']['id']
                self.assertTrue(command_id)
                remove_host_command_ids.append(command_id)

            self.wait_for_commands(chroma_manager, remove_host_command_ids)

        self.verify_cluster_has_no_managed_targets(chroma_manager)

    def verify_cluster_has_no_managed_targets(self, chroma_manager):
        """
        Checks that the database and the hosts specified in the config
        do not have (unremoved) targets for the filesystems specified.
        """
        # Verify there are zero filesystems
        response = chroma_manager.get(
            '/api/filesystem/',
            params = {'limit': 0}
        )
        self.assertTrue(response.successful, response.text)
        filesystems = response.json['objects']
        self.assertEqual(0, len(filesystems))

        # Verify there are zero mgts
        response = chroma_manager.get(
            '/api/target/',
            params = {'kind': 'MGT'}
        )
        self.assertTrue(response.successful, response.text)
        mgts = response.json['objects']
        self.assertEqual(0, len(mgts))

        # Verify there are now zero hosts in the database.
        response = chroma_manager.get(
            '/api/host/',
        )
        self.assertTrue(response.successful, response.text)
        hosts = response.json['objects']
        self.assertEqual(0, len(hosts))

        # Verify there are now zero volumes in the database.
        response = self.chroma_manager.get(
            '/api/volume/',
            params = {'limit': 0}
        )
        self.assertTrue(response.successful, response.text)
        volumes = response.json['objects']
        self.assertEqual(0, len(volumes))

    def reset_accounts(self, chroma_manager):
        """Remove any user accounts which are not in the config (such as
        those left hanging by tests)"""

        configured_usernames = [u['username'] for u in config['chroma_managers'][0]['users']]

        response = chroma_manager.get('/api/user/', data = {'limit': 0})
        self.assertEqual(response.status_code, 200)
        for user in response.json['objects']:
            if not user['username'] in configured_usernames:
                chroma_manager.delete(user['resource_uri'])
