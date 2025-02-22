import datetime
import json
import locale
import os
import re
import traceback

from flask_babel import _, lazy_gettext as _l

from web import app
from web.actions import worker as w, mapping
from common.config import globals
from common.utils import converters, fiat

# Treat *.plot files smaller than this as in-transit (copying) so don't count them
MINIMUM_K32_PLOT_SIZE_BYTES = 100 * 1024 * 1024

PLOT_TABLE_COLUMNS = ['worker', 'blockchain', 'plot_id',  'dir', 'plot', 'type', 'create_date', 'size', 'c', 'a' ]

class Summaries:

    def __init__(self, blockchains, farms, wallets, stats):
        self.rows = []
        for blockchain in blockchains.rows:
            app.logger.info("Adding summary row for {0}".format(blockchain['blockchain']))
            farm = self.find_farm(farms, blockchain['blockchain'])
            if not farm:
                app.logger.error("No farm summary found for {0}".format(blockchain['blockchain']))
                continue
            wallet = self.find_wallet(wallets, blockchain['blockchain'])
            if not wallet:
                app.logger.error("No wallet found for {0}".format(blockchain['blockchain']))
                continue
            if not blockchain['blockchain'] in stats:
                app.logger.error("No blockhain stats for {0} in {1}".format(blockchain['blockchain'], stats.keys()))
                continue
            blockchain_stats = stats[blockchain['blockchain']]
            # Now collect each value in a separate try/except to guard against missing data
            try:
                status = blockchain['status']
            except:
                status = ''
                app.logger.error("No status found for blockchain: {0}".format(blockchain))
            try:
                farmed = farm['total_coins']
            except:
                farmed = ''
                app.logger.error("No total_coins found for farm: {0}".format(farm))
            try:
                wallet_balance_float = wallet['total_balance_float']
                wallet_balance = wallet['total_balance']
            except:
                wallet_balance_float = 0
                wallet_balance = ''
                app.logger.error("No total_balance found for wallet: {0}".format(wallet))
            try:
                height = blockchain['peak_height']
            except:
                height = ''
                app.logger.error("No peak_height found for blockchain: {0}".format(blockchain))
            try:
                height = blockchain['peak_height']
            except:
                height = ''
                app.logger.error("No peak_height found for blockchain: {0}".format(blockchain))
            try:
                plots = farm['plot_count']
            except:
                plots = ''
                app.logger.error("No plot_count found for farm: {0}".format(farm))
            try:
                etw = farm['expected_time_to_win']
            except:
                etw = ''
                app.logger.error("No expected_time_to_win found for farm: {0}".format(farm))
            try:
                harvesters = blockchain_stats['harvesters']
            except:
                harvesters = ''
                app.logger.error("No harvesters found for blockchain stats: {0}".format(blockchain_stats))
            try:
                max_resp = blockchain_stats['max_resp']
            except:
                max_resp = ''
                app.logger.error("No max_resp found for blockchain stats: {0}".format(blockchain_stats))
            try:
                partials_per_hour = blockchain_stats['partials_per_hour']
            except:
                partials_per_hour = ''
                app.logger.error("No partials_per_hour found for blockchain stats: {0}".format(blockchain_stats))
            try:
                edv = blockchain_stats['edv']
            except:
                edv = ''
                app.logger.error("No edv found for blockchain stats: {0}".format(blockchain_stats))
            try:
                edv_fiat = blockchain_stats['edv_fiat']
            except:
                edv_fiat = ''
                app.logger.error("No edv_fiat found for blockchain stats: {0}".format(blockchain_stats))
            self.rows.append({
                'blockchain': blockchain['blockchain'],
                'status': status,
                'farmed': farmed,
                'wallet': wallet_balance,
                'fiat': fiat.to_fiat(blockchain['blockchain'], wallet_balance_float),
                'height': height,
                'plots': plots,
                'harvesters': harvesters, 
                'max_resp': max_resp, 
                'partials_per_hour': partials_per_hour,
                'edv': edv, 
                'edv_fiat': edv_fiat, 
                'etw': self.etw_to_days(blockchain['blockchain'], etw),
            })

    def find_farm(self, farms, blockchain):
        if blockchain in farms:
            return farms[blockchain]

    def find_wallet(self, wallets, blockchain):
        for wallet in wallets.rows:
            if wallet['blockchain'] == blockchain:
                return wallet

    def etw_to_days(self, blockchain, etw):
        if blockchain == 'mmx':
            return ''
        #app.logger.info("{0} -> {1}".format(blockchain, etw))
        try:
            minutes = converters.etw_to_minutes(etw)
            #app.logger.info("Converting {0} minutes.".format(minutes))
            return "%.1f"% round(( minutes / 60 / 24), 2) + " " + _('days')
        except Exception as ex:
            app.logger.info("Unable to convert ETW to minutes '{0}' because {1}.".format(etw, str(ex)))
            return etw

class FarmSummary:

    def __init__(self, farm_recs, wallet_recs):
        self.farms = {}
        self.wallets = Wallets(wallet_recs)
        for farm_rec in farm_recs: 
            if farm_rec.mode == "fullnode":
                try:
                    app.logger.debug("Searching for worker with hostname '{0}'".format(farm_rec.hostname))
                    wkr = w.get_worker(farm_rec.hostname, farm_rec.blockchain)
                    if wkr:
                        displayname = wkr.displayname
                        connection_status = wkr.connection_status()
                    else:
                        app.logger.info("Unable to find a worker with hostname '{0}' and blockchain '{1}'".format(farm_rec.hostname, farm_rec.blockchain))
                        displayname = farm_rec.hostname
                        connection_status = None
                except Exception as ex:
                    app.logger.info("FarmSummary.init(): Error finding a worker with hostname '{0}' and blockchain '{1}'".format(farm_rec.hostname, farm_rec.blockchain))
                    displayname = farm_rec.hostname
                    connection_status = None
                try:
                    if farm_rec.blockchain == 'mmx':
                        wallet_balance = self.wallets.sum_mmx_wallet_balance(farm_rec.hostname, farm_rec.blockchain)
                    else:
                        wallet_balance = self.wallets.sum_chia_wallet_balance(farm_rec.hostname, farm_rec.blockchain)
                except: 
                    wallet_balance = '?'
                if farm_rec.total_coins:
                    total_coins = converters.round_balance(farm_rec.total_coins)
                else:
                    total_coins = converters.round_balance(0)
                farm = {
                    "plot_count": int(farm_rec.plot_count),
                    "plots_size": farm_rec.plots_size,
                    "plots_display_size": converters.gib_to_fmt(farm_rec.plots_size),
                    "status": farm_rec.status,
                    "display_status": self.status_if_responding(displayname, farm_rec.blockchain, connection_status, farm_rec.status),
                    "total_coins": total_coins,
                    "wallet_balance": converters.round_balance(wallet_balance),
                    "currency_symbol": globals.get_blockchain_symbol(farm_rec.blockchain),
                    "netspace_display_size": '?' if not farm_rec.netspace_size else converters.gib_to_fmt(farm_rec.netspace_size),
                    "netspace_size": farm_rec.netspace_size,
                    "expected_time_to_win": self.i18n_etw(farm_rec.expected_time_to_win),
                }
                if not farm_rec.blockchain in self.farms:
                    self.farms[farm_rec.blockchain] = farm
                else:
                    app.logger.info("Discarding duplicate fullnode blockchain status from {0} - {1}".format(farm_rec.hostname, farm_rec.blockchain))    
            else:
                app.logger.info("Stale farm status for {0} - {1}".format(farm_rec.hostname, farm_rec.blockchain))
        if len(self.farms) == 0:  # Handle completely missing farm summary info 
            self.farms['chia'] = {} # with empty chia farm
        #app.logger.info(self.farms.keys())

    def status_if_responding(self, displayname, blockchain, connection_status, last_status):
        if connection_status == 'Responding':
            if last_status == "Farming":
                return _("Active")
            if last_status == "Syncing":
                return _("Syncing")
            if last_status == "Not available":
                return _("Not available")
            if last_status == "Not synced or not connected to peers":
                return _("Not synced")
            return last_status
        #app.logger.info("Oops! {0} ({1}) had connection_success: {2}".format(displayname, blockchain, connection_status))
        return _("Offline")

    def selected_blockchain(self):
        blockchains = list(self.farms.keys())
        blockchains.sort()
        for blockchain in blockchains:
            if blockchain == globals.enabled_blockchains()[0]:
                return blockchain
        return blockchains[0]

    # This is intentionally verbose to allow Babel to extract each english date unit
    def i18n_etw(self, etw):
        if 'years' in etw:
            etw = etw.replace('years', _('years'))
        if 'year' in etw:
            etw = etw.replace('year', _('year'))
        if 'months' in etw:
            etw = etw.replace('months', _('months'))
        if 'month' in etw:
            etw = etw.replace('month', _('month'))
        if 'weeks' in etw:
            etw = etw.replace('weeks', _('weeks'))
        if 'week' in etw:
            etw = etw.replace('week', _('week'))
        if 'days' in etw:
            etw = etw.replace('days', _('days'))
        if 'day' in etw:
            etw = etw.replace('day', _('day'))
        if 'hours' in etw:
            etw = etw.replace('hours', _('hours'))
        if 'hour' in etw:
            etw = etw.replace('hour', _('hour'))
        if 'minutes' in etw:
            etw = etw.replace('minutes', _('minutes'))
        if 'minute' in etw:
            etw = etw.replace('minute', _('minute'))
        if 'never (no plots)' in etw.lower():
            etw = etw.replace('Never (no plots)', _('Never (no plots)'))
        if 'soon' in etw.lower():
            etw = etw.replace('Soon', _('Soon'))
        if 'and' in etw:
            etw = etw.replace('and', _('and'))
        return etw

class FarmPlots:

    def __init__(self, plots):
        self.columns = PLOT_TABLE_COLUMNS
        self.rows = []
        for plot in plots:
            self.rows.append([
                plot.displayname,  
                plot.blockchain, 
                plot.plot_id, 
                plot.dir,  
                #app.jinja_env.filters['plotnameshortener'](plot.file),
                plot.file,
                plot.type if plot.type else "", 
                plot.created_at, 
                app.jinja_env.filters['bytesfilter'](plot.size),
                self.get_check_cell_value(plot.plot_id, plot.plot_check),
                self.get_analzye_cell_value(plot.plot_id, plot.plot_analyze),
            ])

    def get_analzye_cell_value(self, plot_id, plot_analyze):
        if plot_analyze and plot_analyze != '-':
            return "{0} | {1}".format(plot_analyze, plot_id)
        return ""

    def get_check_cell_value(self, plot_id, plot_check):
        if plot_check and plot_check != '-':
            return "{0} | {1}".format(plot_check, plot_id)
        return ""


class ChallengesChartData:

    def __init__(self, challenges):
        self.labels = []
        datasets = {}
        for challenge in challenges:
            created_at = challenge.created_at.replace(' ', 'T')
            if not created_at in self.labels:
                self.labels.append(created_at)
            host_chain = challenge.hostname
            if not host_chain in datasets:
                datasets[host_chain] = {}
            dataset = datasets[host_chain]
            dataset[created_at] = float(challenge.time_taken.split()[0]) # Drop off the 'secs'
        # Now build a sparse array with null otherwise
        self.data = {}
        for key in datasets.keys():
            self.data[key] = [] 
        for label in self.labels:
            for key in datasets.keys():
                if label in datasets[key]:
                    self.data[key].append(datasets[key][label])
                else:
                    self.data[key].append('null') # Javascript null

class Wallets:

    def __init__(self, wallets, cold_wallet_addresses={}):
        self.wallets = wallets
        self.columns = ['hostname', 'details', 'updated_at']
        self.rows = []
        self.cold_wallet_addresses = cold_wallet_addresses
        for wallet in wallets:
            app.logger.info("Wallets.init(): Parsing wallet for blockchain: {0}".format(wallet.blockchain))
            worker_status = None
            try:
                app.logger.info("Wallets.init(): Found worker with hostname '{0}'".format(wallet.hostname))
                worker = w.get_worker(wallet.hostname, wallet.blockchain)
                worker_status = worker.connection_status()
                displayname = worker.displayname
            except:
                app.logger.info("Wallets.init(): Unable to find a worker with hostname '{0}'".format(wallet.hostname))
                displayname = wallet.hostname
            if wallet.blockchain == 'mmx':
                hot_balance = self.sum_mmx_wallet_balance(wallet.hostname, wallet.blockchain, False)
            else:
                hot_balance = self.sum_chia_wallet_balance(wallet.hostname, wallet.blockchain, False)
            try:
                cold_balance = converters.round_balance(float(wallet.cold_balance))
            except:
                cold_balance = ''
            try:
                total_balance = float(hot_balance) + float(cold_balance)
            except:
                total_balance = hot_balance
            self.rows.append({ 
                'displayname': displayname, 
                'hostname': wallet.hostname,
                'blockchain': wallet.blockchain,
                'status': self.extract_status(wallet.blockchain, wallet.details, worker_status),
                'details': wallet.details, 
                'hot_balance': converters.round_balance(hot_balance),
                'cold_balance': cold_balance,
                'cold_address': ','.join(cold_wallet_addresses[wallet.blockchain]) if wallet.blockchain in cold_wallet_addresses else '',
                'total_balance_float': total_balance,
                'total_balance': converters.round_balance(total_balance),
                'blockchain_symbol': globals.get_blockchain_symbol(wallet.blockchain).lower(),
                'fiat_balance': fiat.to_fiat(wallet.blockchain, total_balance),
                'updated_at': wallet.updated_at }) 

    def exclude_cat_wallets(self, wallet_details):
        skip = 0
        details = []
        for line in wallet_details.split('\n'):
            if "type CAT" in line:
                skip = 3 # Skip next 3 lines for this CAT wallet
            elif skip > 0:
                skip = skip -1 
            else:
                details.append(line)
        return '\n'.join(details)

    def sum_chia_wallet_balance(self, hostname, blockchain, include_cold_balance=True):
        numeric_const_pattern = '-Total\sBalance:\s+((?: (?: \d* \. \d+ ) | (?: \d+ \.? ) )(?: [Ee] [+-]? \d+ )?)'
        rx = re.compile(numeric_const_pattern, re.VERBOSE)
        sum = 0
        for wallet in self.wallets:
            if wallet.hostname == hostname and wallet.blockchain == blockchain:
                try:
                    for balance in rx.findall(self.exclude_cat_wallets(wallet.details)):
                        #app.logger.info("Found balance of {0} for for {1} - {2}".format(balance, 
                        # wallet.hostname, wallet.blockchain))
                        sum += locale.atof(balance)
                        found_balance = True
                except Exception as ex:
                    app.logger.info("Failed to find current wallet balance number for {0} - {1}: {2}".format(
                        wallet.hostname, wallet.blockchain, str(ex)))
                if include_cold_balance and wallet.cold_balance:
                    sum += locale.atof(wallet.cold_balance)
        return sum

    def sum_mmx_wallet_balance(self, hostname, blockchain, include_cold_balance=True):
        numeric_const_pattern = 'Balance:\s+((?: (?: \d*\.\d+ ) | (?: \d+\.? ) )(?: [Ee] [+-]? \d+ )?)'
        rx = re.compile(numeric_const_pattern, re.VERBOSE)
        sum = 0
        for wallet in self.wallets:
            if wallet.hostname == hostname and wallet.blockchain == blockchain:
                try:
                    #app.logger.info(wallet.details)
                    for balance in rx.findall(wallet.details):
                        #app.logger.info("Found balance of {0} for for {1} - {2}".format(balance, wallet.hostname, wallet.blockchain))
                        sum += locale.atof(balance)
                        found_balance = True
                except Exception as ex:
                    app.logger.info("Failed to find current wallet balance number for {0} - {1}: {2}".format(
                        wallet.hostname, wallet.blockchain, str(ex)))
                if include_cold_balance and wallet.cold_balance:
                    sum += locale.atof(wallet.cold_balance)
        return sum

    def extract_status(self, blockchain, details, worker_status):
        if worker_status == 'Responding':
            if not details:
                return None
            if blockchain == 'mmx':
                pattern = '^Synced: (.*)$'
            else:
                pattern = '^Sync status: (.*)$'
            for line in details.split('\n'):
                m = re.match(pattern, line)
                if m:
                    status = m.group(1).strip()
                    if 'Yes' == status: # MMX
                        return "Synced"
                    if 'No' == status: # MMX
                        return "Syncing" 
                    return status
        return "Offline"

class Keys:

    def __init__(self, keys):
        self.columns = ['hostname', 'details', 'updated_at']
        self.rows = []
        for key in keys:
            worker_status = None
            try:
                app.logger.debug("Found worker with hostname '{0}'".format(key.hostname))
                worker = w.get_worker(key.hostname, key.blockchain)
                worker_status = worker.connection_status()
                displayname = worker.displayname
            except:
                app.logger.info("Keys.init(): Unable to find a worker with hostname '{0}'".format(key.hostname))
                displayname = key.hostname
            self.rows.append({ 
                'displayname': displayname, 
                'hostname': key.hostname,
                'blockchain': key.blockchain,
                'status': worker_status,
                'details': key.details,
                'updated_at': key.updated_at }) 

class Blockchains:

    def __init__(self, blockchains):
        self.columns = ['hostname', 'blockchain', 'details', 'updated_at']
        self.rows = []
        for blockchain in blockchains:
            worker_status = None
            try:
                app.logger.debug("Found worker with hostname '{0}'".format(blockchain.hostname))
                worker = w.get_worker(blockchain.hostname, blockchain.blockchain)
                worker_status = worker.connection_status()
                displayname = worker.displayname
            except:
                app.logger.info("Blockchains.init(): Unable to find a worker with hostname '{0}'".format(blockchain.hostname))
                displayname = blockchain.hostname
            self.rows.append({ 
                'displayname': displayname, 
                'hostname': blockchain.hostname,
                'blockchain': blockchain.blockchain, 
                'status': self.extract_status(blockchain.blockchain, blockchain.details, worker_status),
                'peak_height': self.extract_height(blockchain.blockchain, blockchain.details),
                'peak_time': self.extract_time(blockchain.blockchain, blockchain.details),
                'details': blockchain.details,
                'updated_at': blockchain.updated_at }) 
    
    def extract_status(self, blockchain, details, worker_status):
        if worker_status == 'Responding':
            if not details:
                return None
            if blockchain == 'mmx':
                pattern = '^Synced: (.*)$'
            else:
                pattern = '^Current Blockchain Status: (.*)$'
            for line in details.split('\n'):
                m = re.match(pattern, line)
                if m: 
                    status = m.group(1).strip()
                    if status == "Full Node Synced":
                        return "Synced"
                    if 'Syncing' in status:
                        return "Syncing"
                    if 'Not Synced' in status:
                        return 'Not Synced'
                    if 'Yes' == status: # MMX
                        return "Synced"
                    if 'No' == status: # MMX
                        return "Syncing" 
                    return status
        return "Offline"

    def extract_height(self, blockchain, details):
        if not details:
            return None
        if blockchain == 'mmx':
            pattern = '^Height: (\d+)$'
        else:
            pattern = '^.* Height:\s+(\d+)$'
        for line in details.split('\n'):
            m = re.match(pattern, line)
            if m: 
                return m.group(1).strip()
        return None

    def extract_time(self, blockchain, details):
        if not details:
            return None
        if blockchain == 'mmx':
            return '-' # None for MMX
        pattern = '^\s+Time:\s+(.*)\sHeight:.*$'
        for line in details.split('\n'):
            m = re.match(pattern, line)
            if m:
                try:
                    peak_time = datetime.datetime.strptime(m.group(1).strip(), '%a %b %d %Y %H:%M:%S %Z')
                    return peak_time.strftime("%Y-%m-%d %H:%M")
                except:
                    return m.group(1).strip() # Unconverted time
        return None

class Connections:

    def __init__(self, connections, lang):
        self.rows = []
        self.blockchains = {}
        geoip_cache = mapping.load_geoip_cache()
        for connection in connections:
            worker_status = None
            try:
                app.logger.debug("Found worker with hostname '{0}'".format(connection.hostname))
                worker = w.get_worker(connection.hostname, connection.blockchain)
                worker_status = worker.connection_status()
                displayname = worker.displayname
            except:
                app.logger.info("Connections.init(): Unable to find a worker with hostname '{0}'".format(connection.hostname))
                displayname = connection.hostname
            self.rows.append({
                'displayname': displayname, 
                'hostname': connection.hostname,
                'blockchain': connection.blockchain,
                'status': worker_status,
                'farmer_port': self.blockchain_port(connection.blockchain),
                'details': connection.details,
                'add_exmample': self.get_add_connection_example(connection.blockchain)
            })
            if connection.blockchain == 'mmx':
                self.blockchains[connection.blockchain] = self.parse_mmx(connection, connection.blockchain, geoip_cache, lang)
            else:
                self.blockchains[connection.blockchain] = self.parse_chia(connection, connection.blockchain, geoip_cache, lang)
        self.rows.sort(key=lambda conn: conn['blockchain'])
    
    def get_add_connection_example(self, blockchain):
        if blockchain == 'btcgreen':
            return "155.133.91.176:9282"
        if blockchain == 'cactus':
            return "101.127.109.238:11444"
        if blockchain == 'chia':
            return "node.chia.net:8444"
        if blockchain == 'chives':
            return "106.225.229.73:9699"
        if blockchain == 'cryptodoge':
            return "46.75.50.16:15994"
        if blockchain == 'flax':
            return "143.198.76.157:6888"
        if blockchain == 'flora':
            return "186.123.88.33:18644"
        if blockchain == 'hddcoin':
            return "145.1.235.18:28444"
        if blockchain == 'maize':
            return "212.159.183.209:8644"
        if blockchain == 'nchain':
            return "218.88.205.216:58445"     
        if blockchain == 'shibgreen':
            return "218.89.239.144:7442"
        if blockchain == 'silicoin':
            return "67.172.84.54:22222"
        if blockchain == 'staicoin':
            return "173.54.12.193:1999"
        if blockchain == 'stor':
            return "118.33.225.159:8668"
        
    def blockchain_port(self,blockchain):
        if blockchain == 'btcgreen':
            return 9282
        if blockchain == 'cactus':
            return 11444
        if blockchain == 'chia':
            return 8444
        if blockchain == 'chives':
            return 9699
        if blockchain == 'cryptodoge':
            return 15994
        if blockchain == 'flax':
            return 6888
        if blockchain == 'flora':
            return 18644
        if blockchain == 'hddcoin':
            return 28444
        if blockchain == 'nchain':
            return 58445
        if blockchain == 'mmx':
            return 12334
        if blockchain == 'maize':
            return 8644
        if blockchain == 'silicoin':
            return 22447
        if blockchain == 'shibgreen':
            return 7442
        if blockchain == 'silicoin':
            return 22222
        if blockchain == 'staicoin':
            return 1999
        if blockchain == 'stor':
            return 8668
        raise("Unknown blockchain fork of selected: " + blockchain)

    def get_geoname_for_lang(self, ip, location, lang):
        lang_codes = [ lang, ]
        if '_' in lang: 
            lang_codes.append(lang.split('_')[0]) # Secondarily, add more generic code
        for lang_code in lang_codes:
            for key in location:
                if key.startswith(lang_code): # Note, means a pt_PT user may get pt_BR as that's the only 'pt' that Maxmind provides
                    #app.logger.info('Found matching geoname for {0} in {1}'.format(lang, location))
                    return location[key]
        if 'en' in location: # Default fallback is 'en'
            app.logger.info('Falling back to English geoname at {0} for {1} in {2}'.format(ip, lang, location))
            return location['en']
        app.logger.debug('Unable to find a geoname at {0} for {1} in {2}'.format(ip, lang, location))
        return '' # Blank if no such match

    def set_geolocation(self, geoip_cache, connection, lang):
        latitude = None
        longitude = None
        city = ''
        country = ''
        if connection['ip'] in geoip_cache and geoip_cache[connection['ip']]:
            geoip = geoip_cache[connection['ip']]
            latitude = geoip['latitude']
            longitude = geoip['longitude']
            try:
                city = self.get_geoname_for_lang(connection['ip'], geoip['city'], lang)
            except:
                traceback.print_exc()
            try:
                country = self.get_geoname_for_lang(connection['ip'], geoip['country'], lang)
            except:
                traceback.print_exc()
        connection['latitude'] = latitude
        connection['longitude'] = longitude
        connection['city'] = city
        connection['country'] = country

    def parse_chia(self, connection, blockchain, geoip_cache, lang):
        conns = []
        for line in connection.details.split('\n'):
            try:
                if line.strip().startswith('Connections:') or \
                    line.strip().startswith('Connection error.') or \
                    line.strip().startswith('This is normal if full node'):
                    pass
                elif line.strip().startswith('Type'):
                    self.columns = line.lower().replace('last connect', 'last_connect') \
                        .replace('mib up|down', 'mib_up mib_down').strip().split()
                elif line.strip().startswith('-SB Height') or line.strip().startswith('-Height'):
                    groups = re.search("Height:\s+(\d+)\s+-Hash:\s+(\w+)...", line.strip())
                    if not groups:
                        app.logger.info("Malformed Height line: {0}".format(line))
                    else:
                        height = groups[1]
                        hash = groups[2]
                        connection['height'] = height
                        connection['hash'] = hash
                        conns.append(connection)
                elif len(line.strip()) == 0:
                    pass
                else:
                    vals = line.strip().split()
                    if len(vals) > 7:
                        last_connect = str(datetime.datetime.today().year) + ' ' + vals[4] + ' ' + vals[5] + ' ' + vals[6]
                        connection = {
                            'type': vals[0],
                            'ip': vals[1],
                            'ports': vals[2],
                            'nodeid': vals[3].replace('...',''),
                            'last_connect': datetime.datetime.strptime(last_connect, '%Y %b %d %H:%M:%S'),
                            'mib_up': float(vals[7].split('|')[0]),
                            'mib_down': float(vals[7].split('|')[1])
                        }
                        if len(vals) > 9: # HDDCoin keeps SBHeight and Hash on same line
                            connection['height'] = vals[8]
                            connection['hash'] = vals[9]
                        try:
                            self.set_geolocation(geoip_cache, connection, lang)
                        except:
                            traceback.print_exc()
                        if blockchain == 'hddcoin' or vals[0] != "FULL_NODE":  # FARMER and WALLET only on one line 
                            conns.append(connection)
                    else:
                        app.logger.info("Bad connection line: {0}".format(line))
            except:
                app.logger.info("Exception parsing connection line: {0}".format(line))
                app.logger.info(traceback.format_exc())
        return conns

    def parse_mmx(self, connection, blockchain, geoip_cache, lang):
        conns = []
        for line in connection.details.split('\n'):
            try:
                #app.logger.info(line)
                m = re.match("\[(.+)\]\s+height\s+=\s+(\!?\d+), (\w+) \(\d+\.\d+\), (\d+\.?\d*) (\w)B/s recv, (\d*\.?\d*) (\w)B/s send,.* since (\d+) min, .* (\d+\.?\d?) sec timeout", line.strip(), re.IGNORECASE)
                if m:
                    connection = {
                        'type': m.group(3),
                        'ip': m.group(1),
                        'height': m.group(2),
                        'ports': '',
                        'nodeid': '',
                        'last_connect': 'since {0} min'.format(m.group(8)),
                        'mib_up': "%.1f"% round(self.rate_to_mb(m.group(6), m.group(7)) * int(m.group(8)) * 60, 2),
                        'mib_down': "%.1f"% round(self.rate_to_mb(m.group(4), m.group(5)) * int(m.group(8)) * 60, 2),
                        'timeout': m.group(9)
                    }
                    try:
                        self.set_geolocation(geoip_cache, connection, lang)
                    except:
                        traceback.print_exc()
                    conns.append(connection)
                elif line.strip():
                    app.logger.info("Bad peer line: {0}".format(line))
            except:
                app.logger.info(traceback.format_exc())
        return conns

    def rate_to_mb(self, rate, unit):
        if unit.lower() == 'k':
            try:
                return float(rate) / 1024
            except:
                app.logger.error("Invalid transmission rate in KB/sec provided: {0}".format(rate))
                return rate
        elif unit.lower() == 'm':
            return float(rate)
        else:
            app.logger.error("Unknown transmission rate unit character of {0} encountered.".format(unit))
            return rate
