
import json
import logging
import os
import requests
import traceback
import re
from html.parser import HTMLParser

# extract tag for grafana alert from evalMatches
# grafana current value on OK
# set service for grafana alerts

LOG = logging.getLogger('alerta.plugins.askap')

try:
    from jinja2 import Template
except Exception as e:
    LOG.error('SLACK: ERROR - Jinja template error: %s, template functionality will be unavailable', e)

try:
    from alerta.plugins import app  # alerta >= 5.0
except ImportError:
    from alerta.app import app  # alerta < 5.0

from alerta.plugins import PluginBase


# ASKAP alert mapping plugin options
ALERT_SEVERITY_MAP = app.config.get('ASKAP_ALERT_SEVERITY_MAP', dict())
GRAFANA_URL = app.config.get('GRAFANA_URL', 'http://localhost')

# SLACK plugin options
SLACK_WEBHOOK_URL = os.environ.get(
    'SLACK_WEBHOOK_URL') or app.config['SLACK_WEBHOOK_URL']
SLACK_ATTACHMENTS = True if os.environ.get(
    'SLACK_ATTACHMENTS', 'False') == 'True' else app.config.get('SLACK_ATTACHMENTS', False)
SLACK_CHANNEL = os.environ.get(
    'SLACK_CHANNEL') or app.config.get('SLACK_CHANNEL', '')
try:
    SLACK_CHANNEL_ENV_MAP = json.loads(
        os.environ.get('SLACK_CHANNEL_ENV_MAP'))
except Exception as e:
    SLACK_CHANNEL_ENV_MAP = app.config.get('SLACK_CHANNEL_ENV_MAP', dict())

SLACK_SERVICE_CHANNELS = app.config.get('SLACK_SERVICE_CHANNELS', False)

ALERTA_USERNAME = os.environ.get(
    'ALERTA_USERNAME') or app.config.get('ALERTA_USERNAME', 'alerta')
SLACK_SEND_ON_ACK = os.environ.get(
    'SLACK_SEND_ON_ACK') or app.config.get('SLACK_SEND_ON_ACK', False)
SLACK_SEVERITY_MAP = app.config.get('SLACK_SEVERITY_MAP', {})
SLACK_DEFAULT_SEVERITY_MAP = {'security': '#000000', # black
                              'critical': '#FF0000', # red
                              'major': '#FFA500', # orange
                              'minor': '#FFFF00', # yellow
                              'warning': '#1E90FF', #blue
                              'informational': '#808080', #gray
                              'debug': '#808080', # gray
                              'trace': '#808080', # gray
                              'ok': '#00CC00'} # green
SLACK_SUMMARY_FMT = app.config.get('SLACK_SUMMARY_FMT', None)  # Message summary format
SLACK_DEFAULT_SUMMARY_FMT='{icon} *[{status}] {severity}* - <{dashboard}/#/alert/{alert_id}|{event} on {resource}>'
ICON_EMOJI = os.environ.get('ICON_EMOJI') or app.config.get(
    'ICON_EMOJI', ':rocket:')
SLACK_PAYLOAD = app.config.get('SLACK_PAYLOAD', None)  # Full API control
DASHBOARD_URL = os.environ.get(
    'DASHBOARD_URL') or app.config.get('DASHBOARD_URL', '')
SLACK_HEADERS = {
    'Content-Type': 'application/json'
}
SLACK_TOKEN = os.environ.get('SLACK_TOKEN') or app.config.get('SLACK_TOKEN',None)
if SLACK_TOKEN:
    SLACK_HEADERS['Authorization'] = 'Bearer ' + SLACK_TOKEN

SLACK_ICONS = {
        'OK' : ':ok_hand:',
        'MINOR' : ':bomb:',
        'MAJOR' : ':boom:'}

def _make_url_params_from_tags(alert):
    params = ""
    join="?"
    LOG.info("alert tags : {0}".format(alert.tags))
    for tag in alert.tags:
        if '=' in tag:
            k,v = tag.split('=')
            params += "{0}var-{1}={2}".format(join,k,v)
            join  = "&"
    return params

class LinkParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self._href = None
        self._title = None

    def handle_starttag(self, tag, attrs):
        for attr in attrs:
            if attr[0] == 'href':
                self._href = attr[1]

    def handle_data(self, data):
        self._title = data

    def get_href(self):
        return self._href

    def get_title(self):
        return self._title

class ServiceIntegration(PluginBase):

    def __init__(self, name=None):
        # override user-defined severities
        self._severities = SLACK_DEFAULT_SEVERITY_MAP
        self._severities.update(SLACK_SEVERITY_MAP)

        super(ServiceIntegration, self).__init__(name)

    def pre_receive(self, alert):
        LOG.debug('processing alert {0} sev {1} x'.format(alert.event,alert.severity))

        # map alert levels to the 'EPICS' alert levels we define in alertad.conf
        if alert.severity in ALERT_SEVERITY_MAP:
            alert.severity = ALERT_SEVERITY_MAP[alert.severity]
            LOG.debug('new sev {0}'.format(alert.severity))

        if alert.origin == "kapacitor":
            # add a Grafana dashboard link for Kapacitor generated alerts
            dashboard=alert.event.replace(' ', '-')
            alert.attributes['Grafana Dashboard'] = '<a target="_blank" rel="noopener noreferrer" href="{0}/d/{1}/{2}{3}">{1}</a>'.format(
                    GRAFANA_URL,
                    dashboard,
                    dashboard.lower(),
                    _make_url_params_from_tags(alert))
        elif alert.origin == "Grafana" and 'ruleUrl' in alert.attributes:
            # modify URL attribute from Grafana alert to be same as kapacitor alerts
            LOG.debug("ruleUrl is {0}".format(alert.attributes['ruleUrl']))
            alert.attributes['Grafana Dashboard'] = alert.attributes['ruleUrl']
            alert.attributes.pop('ruleUrl', None)

            # look for service tag in message 
            # to route to correct channel
            parts=re.split('.*service\ *=\ *', alert.text)
            if len(parts) > 1:
                alert.service = [parts[1]]

        return alert

    def _format_template(self, templateFmt, templateVars):
        try:
            LOG.debug('SLACK: generating template: %s' % templateFmt)
            template = Template(templateFmt)
        except Exception as e:
            LOG.error('SLACK: ERROR - Template init failed: %s', e)
            return

        try:
            LOG.debug('SLACK: rendering template: %s' % templateFmt)
            LOG.debug('SLACK: rendering variables: %s' % templateVars)
            return template.render(**templateVars)
        except Exception as e:
            LOG.error('SLACK: ERROR - Template render failed: %s', e)
            return

    def _slack_prepare_payload(self, alert, status=None, text=None):

        if alert.severity in self._severities:
            color = self._severities[alert.severity]
        else:
            color = '#00CC00'  # green

        if SLACK_SERVICE_CHANNELS:
            channel = '#{0}'.format(alert.service[0].lower().replace('.', '_').replace(' ', '_'))
        else:
            channel = SLACK_CHANNEL_ENV_MAP.get(alert.environment, SLACK_CHANNEL)

        templateVars = {
            'alert': alert,
            'status': status if status else alert.status,
            'config': app.config,
            'color': color,
            'channel': channel,
            'emoji': ICON_EMOJI,
        }

        if SLACK_PAYLOAD:
            LOG.debug("Formatting with slack payload template")
            formattedPayload = self._format_template(json.dumps(SLACK_PAYLOAD), templateVars).replace('\n', '\\n')
            LOG.debug("Formatted slack payload:\n%s" % formattedPayload)
            payload = json.loads(formattedPayload)
        else:
            if type(SLACK_SUMMARY_FMT) is str:
                summary = self._format_template(SLACK_SUMMARY_FMT, templateVars)
            else:
                summary = SLACK_DEFAULT_SUMMARY_FMT.format(
                    icon=SLACK_ICONS.get(alert.severity, ':question:'),
                    status=(status if status else alert.status).capitalize(),
                    environment=alert.environment.upper(),
                    service=','.join(alert.service),
                    severity=alert.severity,
                    event=alert.event,
                    resource=alert.resource,
                    alert_id=alert.id,
                    short_id=alert.get_id(short=True),
                    dashboard=DASHBOARD_URL
                )
            if not SLACK_ATTACHMENTS:
                payload = {
                    "username": ALERTA_USERNAME,
                    "channel": channel,
                    "text": summary,
                    "icon_emoji": ICON_EMOJI
                }
            else:
                dashboard=alert.event.replace(' ', '-')
                fields = []
                if 'Grafana Dashboard' in alert.attributes:
                    parser = LinkParser()
                    parser.feed(alert.attributes['Grafana Dashboard'])
                    grafana = '<{0}|{1}>'.format(parser.get_href(), parser.get_title())
                    fields.append({"title": "Grafana", "value": grafana, "short": True})

                fields += [
                        {"title": "Origin", "value": alert.origin, "short": True},
                        {"title": "Subsystem", "value": ", ".join( alert.service), "short": True},
                        {"title": "Value", "value": alert.value, "short": True},
                        {"title": "Text", "value": text or alert.text, "short": True}
                        ]
                for tag in alert.tags:
                    if '=' in tag:
                        k,v = tag.split('=')
                        fields.append({"title": k, "value": v, "short": True})
                payload = {
                    "username": ALERTA_USERNAME,
                    "channel": channel,
                    "icon_emoji": ICON_EMOJI,
                    "text": summary,
                    "attachments": [{
                        "fallback": summary,
                        "color": color,
                        "fields": fields,
                    }]
                }

        return payload

    def post_receive(self, alert):

        if alert.repeat:
            return

        try:
            payload = self._slack_prepare_payload(alert)

            LOG.debug("alert receive alert %s" % alert)
            LOG.debug('Slack payload: %s', payload)
        except Exception as e:
            LOG.error('Exception formatting payload: %s\n%s' % (e, traceback.format_exc()))
            return

        try:
            r = requests.post(SLACK_WEBHOOK_URL,
                              data=json.dumps(payload), headers=SLACK_HEADERS, timeout=2)
        except Exception as e:
            raise RuntimeError("Slack connection error: %s", e)

        LOG.debug('Slack response: %s %s' % (r.status_code, r.text))

    def status_change(self, alert, status, text):
        if SLACK_SEND_ON_ACK == False or status not in ['ack', 'assign']:
            return

        try:
            payload = self._slack_prepare_payload(alert, status, text)

            LOG.debug("alert status change alert %s status %s text %s" % (alert, status, text))
            LOG.debug('Slack payload: %s', payload)
        except Exception as e:
            LOG.error('Exception formatting payload: %s\n%s' % (e, traceback.format_exc()))
            return

        try:
            r = requests.post(SLACK_WEBHOOK_URL,
                              data=json.dumps(payload), headers=SLACK_HEADERS, timeout=2)
        except Exception as e:
            raise RuntimeError("Slack connection error: %s", e)

        LOG.debug('Slack response: %s %s' % (r.status_code, r.text))
