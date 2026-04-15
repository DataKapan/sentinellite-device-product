import json

CONFIG_FILE = "/opt/sentinel/config.json"
VERSION_FILE = "/opt/sentinel/.config_version"
NEW_CONFIG = "/tmp/new_config.json"

try:
    with open(NEW_CONFIG, 'r') as f:
        data = json.load(f)
except:
    exit(0)

config = data.get('config', {})
version = data.get('config_version', 0)
creds = data.get('credentials', {})

try:
    with open(CONFIG_FILE, 'r') as f:
        current = json.load(f)
except:
    current = {}

old_version = 0
try:
    with open(VERSION_FILE, 'r') as f:
        old_version = int(f.read().strip())
except:
    pass

if version <= old_version:
    exit(0)

if 'DETECTION' not in current:
    current['DETECTION'] = {}
if 'CAMERA' not in current:
    current['CAMERA'] = {}
if 'FTP' not in current:
    current['FTP'] = {}
if 'PUSHOVER' not in current:
    current['PUSHOVER'] = {}

if 'camera' in config:
    cam = config['camera']
    res = cam.get('resolution', '1280x720').split('x')
    current['CAMERA']['WIDTH'] = int(res[0])
    current['CAMERA']['HEIGHT'] = int(res[1])
    current['CAMERA']['TYPE'] = cam.get('type', 'standard')
    current['CAMERA']['NOIR_CORRECTION'] = cam.get('noir_correction', True)
    current['CAMERA']['NIGHT_MODE_GRAYSCALE'] = cam.get('night_grayscale', True)

if 'detection' in config:
    det = config['detection']
    thresh = det.get('thresholds', {})
    current['DETECTION']['HUMAN_THRESHOLD_DAY'] = thresh.get('person', 0.45)
    current['DETECTION']['HUMAN_THRESHOLD_NIGHT'] = thresh.get('person', 0.45) - 0.15
    current['DETECTION']['CAR_THRESHOLD'] = thresh.get('vehicle', 0.40)
    current['DETECTION']['TRUCK_THRESHOLD'] = 0.35
    current['ENABLED_CLASSES'] = det.get('enabled_classes', [0, 2, 7])
    current['NOTIFICATIONS'] = det.get('notifications', {})

if 'schedule' in config:
    sch = config['schedule']
    current['SCHEDULE_MODE'] = sch.get('mode', '24/7')
    current['SCHEDULE_START'] = sch.get('start', '00:00')
    current['SCHEDULE_END'] = sch.get('end', '23:59')
    current['NIGHT_START'] = sch.get('night_start', '21:00')
    current['NIGHT_END'] = sch.get('night_end', '06:00')

# Webhook
if 'integrations' in config:
    wh = config['integrations'].get('webhook', {})
    if wh.get('url'):
        current['WEBHOOK'] = {'URL': wh['url']}

if 'integrations' in config:
    intg = config['integrations']
    if intg.get('ftp', {}).get('server'):
        ftp = intg['ftp']
        current['FTP']['SERVER'] = ftp.get('server', '')
        current['FTP']['PORT'] = ftp.get('port', 21)
        current['FTP']['USER'] = ftp.get('username', '')
        current['FTP']['PATH'] = ftp.get('path', '/Sentinel')
    if intg.get('milestone', {}).get('server'):
        ms = intg['milestone']
        current['MILESTONE'] = {
            'ENABLED': True,
            'SERVER': ms.get('server', ''),
            'PORT': ms.get('port', 80),
            'EVENT_SOURCE': ms.get('event_source', ''),
            'ANALYTICS_ID': ms.get('analytics_id', '')
        }

if creds.get('ftp', {}).get('password'):
    current['FTP']['PASS'] = creds['ftp']['password']
if creds.get('pushover', {}).get('app_token'):
    current['PUSHOVER']['TOKEN'] = creds['pushover']['app_token']
if creds.get('pushover', {}).get('group_key'):
    current['PUSHOVER']['GROUP'] = creds['pushover']['group_key']
if creds.get('milestone', {}).get('password'):
    current['MILESTONE']['PASS'] = creds['milestone']['password']

with open(CONFIG_FILE, 'w') as f:
    json.dump(current, f, indent=2)

with open(VERSION_FILE, 'w') as f:
    f.write(str(version))

print(f"Config updated to v{version}")
