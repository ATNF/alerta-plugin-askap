
import logging

from alerta.plugins import PluginBase, app

LOG = logging.getLogger('alerta.plugins.askap')

AlertLevelMap = {
        # kapacitor alerts
        "critical"      : "MAJOR",
        "warning"       : "MINOR",
        "indeterminate" : "INVALID",
        "ok"            : "OK",
        "unknown"       : "INVALID",
        # grafana alerts
        "major"         : "MAJOR"
        }


def make_url_params_from_tags(alert):
    params = ""
    join="?"
    LOG.info("alert tags : {0}".format(alert.tags))
    for tag in alert.tags:
        if '=' in tag:
            k,v = tag.split('=')
            params += "{0}var-{1}={2}".format(join,k,v)
            join  = "&"
    return params

class ModifyAlert(PluginBase):

    def pre_receive(self, alert):

        LOG.info('processing alert {0} sev {1} x'.format(alert.event,alert.severity))

        # map alert levels to the 'EPICS' alert levels we define in alertad.conf
        if alert.severity in AlertLevelMap:
            alert.severity = AlertLevelMap[alert.severity]

        if alert.origin == "kapacitor":
            # add a Grafana dashboard link for Kapacitor generated alerts
            dashboard=alert.event.replace(' ', '-')
            alert.attributes['Grafana Dashboard'] = '<a target="_blank" rel="noopener noreferrer" href="{0}/d/{1}/{2}{3}">{1}</a>'.format(
                    app.config['GRAFANA_URL'],
                    dashboard,
                    dashboard.lower(),
                    make_url_params_from_tags(alert))

        return alert

    def post_receive(self, alert):
        return

    def status_change(self, alert, status, text):
        return
