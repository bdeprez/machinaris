#
# CLI interactions with the chia binary.
#

import datetime
import os
import psutil
import re
import signal
import shutil
import socket
import time
import traceback
import yaml

from flask import Flask, jsonify, abort, request, flash
from stat import S_ISREG, ST_CTIME, ST_MTIME, ST_MODE, ST_SIZE
from subprocess import Popen, TimeoutExpired, PIPE
from os import path

from web import app, db
from common.models import farms as f, plots as p, challenges as c
from common.config import globals
from web.models.chia import FarmSummary, FarmPlots, BlockchainChallenges

CHIA_BINARY = '/chia-blockchain/venv/bin/chia'

def load_farm_summary():
    farms = db.session.query(f.Farm).all()
    return FarmSummary(farms)

def load_plots_farming():
    plots = db.session.query(p.Plot).all()
    return FarmPlots(plots)

def recent_challenges():
    minute_ago = (datetime.datetime.now() - datetime.timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S.000")
    challenges = db.session.query(c.Challenge).filter(c.Challenge.created_at >= minute_ago).order_by(c.Challenge.created_at.desc())
    return BlockchainChallenges(challenges[:8]) # Last minute challenge

def load_wallet_show():
    global last_wallet_show
    global last_wallet_show_load_time
    if last_wallet_show and last_wallet_show_load_time >= \
            (datetime.datetime.now() - datetime.timedelta(seconds=RELOAD_MINIMUM_SECS)):
        return last_wallet_show

    proc = Popen("echo 'S' | {0} wallet show".format(CHIA_BINARY), stdout=PIPE, stderr=PIPE, shell=True)
    try:
        outs, errs = proc.communicate(timeout=90)
    except TimeoutExpired:
        proc.kill()
        proc.communicate()
        abort(500, description="The timeout is expired!")
    if errs:
        abort(500, description=errs.decode('utf-8'))
    last_wallet_show = chia.Wallet(outs.decode('utf-8').splitlines())
    last_wallet_show_load_time = datetime.datetime.now()
    return last_wallet_show

last_blockchain_show = None 
last_blockchain_show_load_time = None 

def load_blockchain_show():
    global last_blockchain_show
    global last_blockchain_show_load_time
    if last_blockchain_show and last_blockchain_show_load_time >= \
            (datetime.datetime.now() - datetime.timedelta(seconds=RELOAD_MINIMUM_SECS)):
        return last_blockchain_show

    proc = Popen("{0} show --state".format(CHIA_BINARY), stdout=PIPE, stderr=PIPE, shell=True)
    try:
        outs, errs = proc.communicate(timeout=90)
    except TimeoutExpired:
        proc.kill()
        proc.communicate()
        abort(500, description="The timeout is expired!")
    if errs:
        abort(500, description=errs.decode('utf-8'))
    
    last_blockchain_show = chia.Blockchain(outs.decode('utf-8').splitlines())
    last_blockchain_show_load_time = datetime.datetime.now()
    return last_blockchain_show

last_connections_show = None 
last_connections_show_load_time = None 

def load_connections_show():
    global last_connections_show
    global last_connections_show_load_time
    if last_connections_show and last_connections_show_load_time >= \
            (datetime.datetime.now() - datetime.timedelta(seconds=RELOAD_MINIMUM_SECS)):
        return last_connections_show

    proc = Popen("{0} show --connections".format(CHIA_BINARY), stdout=PIPE, stderr=PIPE, shell=True)
    try:
        outs, errs = proc.communicate(timeout=90)
    except TimeoutExpired:
        proc.kill()
        proc.communicate()
        abort(500, description="The timeout is expired!")
    if errs:
        abort(500, description=errs.decode('utf-8'))
    
    last_connections_show = chia.Connections(outs.decode('utf-8').splitlines())
    last_connections_show_load_time = datetime.datetime.now()
    return last_connections_show

def add_connection(connection):
    try:
        hostname,port = connection.split(':')
        if socket.gethostbyname(hostname) == hostname:
            app.logger.info('{} is a valid IP address'.format(hostname))
        elif socket.gethostbyname(hostname) != hostname:
            app.logger.info('{} is a valid hostname'.format(hostname))
        proc = Popen("{0} show --add-connection {1}".format(CHIA_BINARY, connection), stdout=PIPE, stderr=PIPE, shell=True)
        try:
            outs, errs = proc.communicate(timeout=90)
        except TimeoutExpired:
            proc.kill()
            proc.communicate()
            abort(500, description="The timeout is expired!")
        if errs:
            abort(500, description=errs.decode('utf-8'))
    except Exception as ex:
        app.logger.info(traceback.format_exc())
        flash('Invalid connection "{0}" provided.  Must be HOST:PORT.'.format(connection), 'danger')
        flash(str(ex), 'warning')
    else:
        app.logger.info("{0}".format(outs.decode('utf-8')))
        flash('Nice! Connection added to Chia and sync engaging!', 'success')

last_keys_show = None 
last_keys_show_load_time = None 

def load_keys_show():
    global last_keys_show
    global last_keys_show_load_time
    if last_keys_show and last_keys_show_load_time >= \
            (datetime.datetime.now() - datetime.timedelta(seconds=RELOAD_MINIMUM_SECS)):
        return last_keys_show

    proc = Popen("{0} keys show".format(CHIA_BINARY), stdout=PIPE, stderr=PIPE, shell=True)
    try:
        outs, errs = proc.communicate(timeout=90)
    except TimeoutExpired:
        proc.kill()
        proc.communicate()
        abort(500, description="The timeout is expired!")
    if errs:
        abort(500, description=errs.decode('utf-8'))
    
    last_keys_show = chia.Keys(outs.decode('utf-8').splitlines())
    last_keys_show_load_time = datetime.datetime.now()
    return last_keys_show 

def generate_key(key_path):
    if os.path.exists(key_path) and os.stat(key_path).st_size > 0:
        app.logger.info('Skipping key generation as file exists and is NOT empty! {0}'.format(key_path))
        flash('Skipping key generation as file exists and is NOT empty!', 'danger')
        flash('key_path={0}'.format(key_path), 'warning')
        return False
    proc = Popen("{0} keys generate".format(CHIA_BINARY), stdout=PIPE, stderr=PIPE, shell=True)
    try:
        outs, errs = proc.communicate(timeout=90)
    except TimeoutExpired:
        proc.kill()
        proc.communicate()
        app.logger.info(traceback.format_exc())
        flash('Timed out while generating keys!', 'danger')
        flash(str(ex), 'warning')
        return False
    if errs:
        app.logger.info("{0}".format(errs.decode('utf-8')))
        flash('Unable to generate keys!', 'danger')
        return False
    proc = Popen("{0} keys show --show-mnemonic-seed | tail -n 1 > {1}".format(CHIA_BINARY, key_path), stdout=PIPE, stderr=PIPE, shell=True)
    try:
        outs, errs = proc.communicate(timeout=90)
    except TimeoutExpired:
        proc.kill()
        proc.communicate()
        app.logger.info(traceback.format_exc())
        flash('Timed out while generating keys!', 'danger')
        flash(str(ex), 'warning')
        return False
    if errs:
        app.logger.info("{0}".format(errs.decode('utf-8')))
        flash('Unable to save mnemonic to {0}'.format(key_path), 'danger')
        return False
    else:
        app.logger.info("Store mnemonic output: {0}".format(outs.decode('utf-8')))
        try:
            mnemonic_words = open(key_path,'r').read().split()
            if len(mnemonic_words) != 24:
                flash('{0} does not contain a 24-word mnemonic!'.format(key_path), 'danger')
                return False
        except:
                flash('{0} was unreadable or not found.'.format(key_path), 'danger')
                return False
        flash('Welcome! A new key has been generated at {0}. Keep it secret! Keep it safe!'.format(key_path), 'success')
        flash('{0}'.format(" ".join(mnemonic_words)), 'info')
    proc = Popen("{0} start farmer".format(CHIA_BINARY), stdout=PIPE, stderr=PIPE, shell=True)
    try:
        outs, errs = proc.communicate(timeout=90)
    except TimeoutExpired:
        proc.kill()
        proc.communicate()
        app.logger.info(traceback.format_exc())
        flash('Timed out while starting farmer! Try restarting the Machinaris container.', 'danger')
        flash(str(ex), 'warning')
        return False
    if errs:
        app.logger.info("{0}".format(errs.decode('utf-8')))
        flash('Unable to start farmer. Try restarting the Machinaris container.'.format(key_path), 'danger')
        flash(str(ex), 'warning')
        return False
    return True

def remove_connection(node_id, ip):
    try:
        proc = Popen("{0} show --remove-connection {1}".format(CHIA_BINARY, node_id), stdout=PIPE, stderr=PIPE, shell=True)
        try:
            outs, errs = proc.communicate(timeout=90)
        except TimeoutExpired:
            proc.kill()
            proc.communicate()
            app.logger.info("The timeout is expired!")
            return False
        if errs:
            app.logger.info(errs.decode('utf-8'))
            return False
        if outs:
            app.logger.info(outs.decode('utf-8'))
    except Exception as ex:
        app.logger.info(traceback.format_exc())
    app.logger.info("Successfully removed connection to {0}".format(ip))
    return True

def compare_plot_counts(global_config, farming, plots):
    if farming:
        try:
            if int(farming.plot_count) < len(plots.rows):
                flash("Warning! Chia is farming {0} plots, but Machinaris found {1} *.plot files on disk. See the <a href='https://github.com/guydavis/machinaris/wiki/FAQ#warning-chia-is-farming-x-plots-but-machinaris-found-y-plot-files-on-disk' target='_blank'>FAQ</a>.".format(farming.plot_count, len(plots.rows), 'warning'))
        except:
            app.logger.info("Compare plots failed to check matching plot counts.")
            app.logger.info(traceback.format_exc())

def is_plots_check_running():
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        if proc.info['name'] == 'chia' and 'plots' in proc.info['cmdline'] and 'check' in proc.info['cmdline']:
            return proc.info['pid']
    return None

def check_plots(first_load):
    output_file = '/root/.chia/mainnet/log/plots_check.log'
    if not is_plots_check_running() and first_load == "true":
        try:
            log_fd = os.open(output_file, os.O_RDWR | os.O_CREAT)
            log_fo = os.fdopen(log_fd, "a+")
            proc = Popen("{0} plots check".format(CHIA_BINARY), shell=True, 
                universal_newlines=True, stdout=log_fo, stderr=log_fo)
        except:
            app.logger.info(traceback.format_exc())
            return 'Failed to start plots check job!'
        else:
            return "Starting chia plots check at " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    else:
        class_escape = re.compile(r' chia.plotting.(\w+)(\s+): ')
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        proc = Popen(['tail', '-n', str(MAX_LOG_LINES), output_file], stdout=PIPE)
        return  class_escape.sub('', ansi_escape.sub('', proc.stdout.read().decode("utf-8")))