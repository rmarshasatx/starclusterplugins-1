"""A starcluster plugin for running an IPython cluster using SGE (requires IPython 0.11, pyzmq)

See ipythondev plugin for installing git master IPython and its dependencies

"""
import time
import posixpath

from starcluster.clustersetup import ClusterSetup
from starcluster.logger import log

def user_ssh(node, user, cmd):
    return node.ssh.execute("su - %s -c '%s'"%(user, cmd))

class IPClusterSetup(ClusterSetup):
    """Start an IPython cluster (IPython 0.11)
    
    See ipythondev plugin for installing dependencies at launch
    """
    
    def _write_config(self, master, user, profile_dir):
        """create cluster config"""
        log.info("Writing IPython cluster config files")
        user_ssh(master, user, 'ipython profile create')
        f = master.ssh.remote_file('%s/ipcontroller_config.py'%profile_dir)
        f.write('\n'.join([
            "c = get_config()",
            "c.HubFactory.ip='%s'"%master.private_ip_address,
            "c.IPControllerApp.ssh_server='%s'"%master.public_dns_name,
            "c.Application.log_level = 'DEBUG'",
            "",
        ]))
        f.close()
        
        f = master.ssh.remote_file('%s/ipcluster_config.py'%profile_dir)
        f.write('\n'.join([
            "c = get_config()",
            "c.IPClusterStart.controller_launcher_class='SGEControllerLauncher'",
            # restrict controller to master node:
            "c.SGEControllerLauncher.queue='all.q@master'",
            "c.IPClusterEngines.engine_launcher_class='SGEEngineSetLauncher'",
            "c.Application.log_level = 'DEBUG'",
            "",
        ]))
        f.close()
        
        f = master.ssh.remote_file('%s/ipengine_config.py'%profile_dir)
        f.write('\n'.join([
            "c = get_config()",
            "c.EngineFactory.timeout = 10",
            "c.Application.log_level = 'DEBUG'",
            "",
        ]))
        f.close()
        
        # root currently owns config files, change to user:
        master.ssh.execute("chown -R %s %s"%(user,profile_dir))
    
    def _start_cluster(self, master, user, n, profile_dir):
        log.info("Starting IPython cluster with %i engines"%n)
        # cleanup existing connection files:
        user_ssh(master, user, "rm -f %s/security/*.json"%profile_dir)
        user_ssh(master, user, """source /etc/profile;
        ipcluster start n=%i delay=10 --daemonize
        """%n
        )
        
        # wait for JSON file to exist
        time.sleep(2)
        json = '%s/security/ipcontroller-client.json'%profile_dir
        while not master.ssh.isfile(json):
            log.info("waiting for JSON connector file...")
            time.sleep(1)
        # retrieve JSON connection info
        master.ssh.sftp.get(json, 'starcluster.json')
    
    def run(self, nodes, master, user, user_shell, volumes):
        tic = time.time()
        n = sum([node.num_processors for node in nodes]) - 1
        user_home = node.getpwnam(user).pw_dir
        profile_dir=posixpath.join(user_home, '.ipython', 'profile_default')
        self._write_config(master, user, profile_dir)
        self._start_cluster(master, user, n, profile_dir)
        mins = (time.time()-tic)/60.
        log.info("%i engine Cluster started in %.2f mins"%(n, mins))
        log.info("""Cluster started, you should be able to connect with:
            from IPython.parallel import Client
            rc = Client('starcluster.json')"""
        )
    
    def _stop_cluster(self, master, user):
        user_ssh(master, user, "ipcluster stop")
        user_ssh(master, user, "pkill ipengine")
        user_ssh(master, user, "pkill ipcontroller")
    
    def on_add_node(self, node, nodes, master, user, user_shell, volumes):
        n = node.num_processors
        log.info("Adding %i engines on %s to ipcluster" % (n, node.alias))
        # user_ssh(node, user, "ipcluster engines n=%i --daemonize" % n)
    
    def on_remove_node(self, node, nodes, master, user, user_shell, volumes):
        log.info("Removing %s from ipcluster" % node.alias)
        node.ssh.execute('pkill ipengine')