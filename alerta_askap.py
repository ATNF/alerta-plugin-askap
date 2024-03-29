
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
from alerta.app import db

# ASKAP alert mapping plugin options
ALERT_SEVERITY_MAP = app.config.get('ASKAP_ALERT_SEVERITY_MAP', dict())
DEFAULT_NORMAL_SEVERITY = app.config.get('DEFAULT_NORMAL_SEVERITY', 'OK')
GRAFANA_URL = app.config.get('GRAFANA_URL', 'http://localhost')

FLAPPING_WINDOW=app.config.get('FLAPPING_WINDOWS', 3600)
FLAPPING_COUNT=app.config.get('FLAPPING_COUNT', 4)

# SLACK plugin options
SLACK_WEBHOOK_URL = os.environ.get(
    'SLACK_WEBHOOK_URL') or app.config['SLACK_WEBHOOK_URL']
SLACK_CHANNEL = os.environ.get(
    'SLACK_CHANNEL') or app.config.get('SLACK_CHANNEL', '')
try:
    SLACK_CHANNEL_ENV_MAP = json.loads(
        os.environ.get('SLACK_CHANNEL_ENV_MAP'))
except Exception as e:
    SLACK_CHANNEL_ENV_MAP = app.config.get('SLACK_CHANNEL_ENV_MAP', dict())

SLACK_SERVICE_CHANNELS = app.config.get('SLACK_SERVICE_CHANNELS', False)

ALERTAWEB_URL = os.environ.get(
        'ALERTAWEB_URL') or app.config.get('ALERTAWEB_URL', '')
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
ICON_EMOJI = os.environ.get('ICON_EMOJI') or app.config.get(
    'ICON_EMOJI', ':rocket:')
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

def _get_dashboard(alert):
    '''
    return a Grafana Dashboard URL either from specified tag or service name
    '''
    uid = alert.event.replace(' ', '-')
    dashboard = uid
    params = ""
    join="?"
    LOG.debug("alert tags : {0}".format(alert.tags))
    for tag in alert.tags:
        if '=' in tag:
            k,v = tag.split('=')
            if k == 'dashboard':
                # override default dashboard
                # with one specified in tag set
                # in Kapacitor rule
                # either as UID only or uid/name
                tmp = v.split('/')
                uid = tmp[0]
                if len(tmp) > 1:
                    dashboard = tmp[1]
                continue
            params += "{0}var-{1}={2}".format(join, k, v)
            join  = "&"

    return '<a target="_blank" rel="noopener noreferrer" href="{0}/d/{1}/{2}{3}">{1}</a>'.format(GRAFANA_URL, uid, dashboard, params)

def _human_time(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    str = ""
    if h > 0:
        str += "{0}h ".format(h)
    if m > 0:
        str += "{0}m ".format(m)
    if s > 0:
        str += "{0}s ".format(s)
    return str.strip()

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

    def pre_receive(self, alert, **kwargs):
        LOG.debug('processing alert {0} sev {1} x'.format(alert.event,alert.severity))

        # map alert levels to the 'EPICS' alert levels we define in alertad.conf
        if alert.severity in ALERT_SEVERITY_MAP:
            alert.severity = ALERT_SEVERITY_MAP[alert.severity]
            LOG.debug('new sev {0}'.format(alert.severity))

        if alert.origin == "kapacitor":
            # add a Grafana dashboard link for Kapacitor generated alerts
            alert.attributes['Grafana Dashboard'] = _get_dashboard(alert)
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

        icon = SLACK_ICONS.get(alert.severity, ':question:')
        status = (status if status else alert.status).capitalize()
        flapnotify = ""
        if alert.attributes.get("flapping", False):
            icon = ":bird:"
            status = "FLAPPING"
            flapnotify= " is flapping, suppressing further notifications"

        summary = '{icon} *[{status}] {severity}* - <{alerta}/#/alert/{alert_id}|{event} on {resource}{flapnotify}>'.format(
            icon=icon,
            status=status,
            severity=alert.severity,
            alerta=ALERTAWEB_URL,
            alert_id=alert.id,
            event=alert.event,
            resource=alert.resource,
            flapnotify=flapnotify
        )

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
                if k == 'dashboard':
                    continue
                fields.append({"title": k, "value": v, "short": True})

        if alert.attributes.get("flapping", False):
            flapmsg = "alert has flapped more than {0} times in the last {1}".format(
                    FLAPPING_COUNT,
                    _human_time(FLAPPING_WINDOW))
            fields.append({"title": "flapping", "value": flapmsg, "short": True})

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

    def post_receive(self, alert, **kwargs):

        if alert.repeat:
            return

        flapnotify = False
        if alert.is_flapping(window=FLAPPING_WINDOW, count=FLAPPING_COUNT):
            if alert.severity != DEFAULT_NORMAL_SEVERITY:
                if not alert.attributes.get('flapping', False):
                    # notify if it has transitioned to flapping
                    LOG.debug("ALERT HAS STARTED TO FLAP")
                    flapnotify = True

                alert.attributes['flapping'] = True
        else:
            alert.attributes['flapping'] = False
            flapnotify = True

        # alert updates in post_receive need 
        # to be saved back into the databbase
        db.update_attributes(alert.id, {}, alert.attributes)

        if alert.attributes.get('flapping', False) and not flapnotify:
            LOG.info("SUPRESSING notification due to flapping")
            return

        try:
            payload = self._slack_prepare_payload(alert)
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

    def status_change(self, alert, status, text, **kwargs):
        if SLACK_SEND_ON_ACK == False or status not in ['ack', 'assign']:
            return

        try:
            payload = self._slack_prepare_payload(alert, status, text)

            LOG.debug("alert status change alert %s status %s text %s" % (alert, status, text))
            LOG.info('Slack payload: %s', payload)
        except Exception as e:
            LOG.error('Exception formatting payload: %s\n%s' % (e, traceback.format_exc()))
            return

        try:
            r = requests.post(SLACK_WEBHOOK_URL,
                              data=json.dumps(payload), headers=SLACK_HEADERS, timeout=2)
        except Exception as e:
            raise RuntimeError("Slack connection error: %s", e)

        LOG.debug('Slack response: %s %s' % (r.status_code, r.text))
