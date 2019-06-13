Modfiy Incomming Alerts for ASKAP
=================================

Modify incomming alerts for ASKAP:

1. Change Kapacitor Alert Levels - Modify the default kapacitor alert
levels to the "EPICS" alert levels of OK,MINOR,MAJOR

2. Add Grafana Dashboard links to Kapacitor Generated Alerts. There must exist
a Grafana Dashboard with the same name as the event name, e.g. "PAF Health".
Furthermore the Grafana Dashboard UID must be set to be the same as the 
Grafana Dashboard name.

Installation
------------

Clone the GitHub repo and run:

    $ python setup.py install

Or, to install remotely from GitHub run:

    $ pip install git+https://github.com/atnf/alerta-plugin-askap.git

Note: If Alerta is installed in a python virtual environment then plugins
need to be installed into the same environment for Alerta to dynamically
discover them.

Configuration
-------------

Add `askap` to the list of enabled `PLUGINS` in `alertad.conf` server
configuration file and set plugin-specific variables either in the
server configuration file or as environment variables.

```python
PLUGINS = ['askap']
```
set the GRAFANA_URL environment variable to the Grafana instance to link to, e.g.

**Example**

```python
GRAFANA_URL = 'http://mygrafana:3000'
```

Troubleshooting
---------------

Restart Alerta API and confirm that the plugin has been loaded and enabled.

Set `DEBUG=True` in the `alertad.conf` configuration file and look for log
entries similar to below:

```
2016-11-20 19:46:15,492 - alerta.plugins[4297]: DEBUG - Server plug-in 'askap' found. [in /var/lib/.virtualenvs/alerta/lib/python2.7/site-packages/alerta_server-4.8.11-py2.7.egg/alerta/plugins/__init__.py:50]
2016-11-20 19:46:15,493 - alerta.plugins[4297]: INFO - Server plug-in 'askap' enabled. [in /var/lib/.virtualenvs/alerta/lib/python2.7/site-packages/alerta_server-4.8.11-py2.7.egg/alerta/plugins/__init__.py:57]
```

References
----------

  * https://www.atnf.csiro.au/projects/askap/index.html
