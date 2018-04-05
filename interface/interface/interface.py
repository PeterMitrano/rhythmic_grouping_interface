import json
import os

import numpy as np
import shutil
import sqlite3
from collections import OrderedDict
from datetime import datetime

import click
import requests
from colorama import init, Fore, Style
from flask import Flask, render_template, g, request, Response, url_for, redirect

app = Flask(__name__)
app.config.from_object(__name__)

app.config.update(dict(
    DATABASE=os.path.join(app.root_path, 'db', 'interface.db'),
    SECRET_KEY='C796D37C6D491E8F0C6E9B83EED34C15C0F377F9F0F3CBB3216FBBF776DA6325',
    USERNAME='admin',
    PASSWORD='password'
))

DEFAULT_SAMPLES_PER_PARTICIPANT = 15
SAMPLES_URL_PREFIX = 'https://mprlab.wpi.edu/samples/'
APP_ROOT = os.path.dirname(os.path.abspath(__file__))  # refers to application_top
APP_STATIC = os.path.join(APP_ROOT, 'static')


@app.cli.command('dumpdb')
@click.option('--outfile', help="name for output file containing the responses database", type=click.Path())
def dumpdb_command(outfile):
    """ Print the database (can save to CSV) """
    dump_db(outfile)


@app.cli.command('remove')
@click.argument('sample_name')
@click.option('--force/--no-force', help='force remove something even if it has responses', default=False)
def remove_command(sample_name, force):
    remove_from_sample_db(sample_name, force)


@app.cli.command('load')
def load_command():
    """Loads new samples into the samples table."""
    success = load()

    if success:
        dump_db(False)


@app.cli.command('initdb')
def initdb_command():
    """Initializes the database."""
    success = init_db()

    if success:
        dump_db(False)


def connect_db():
    """Connects to the specific database."""
    rv = sqlite3.connect(app.config['DATABASE'], detect_types=sqlite3.PARSE_DECLTYPES)
    rv.row_factory = sqlite3.Row
    return rv


def get_db():
    """Opens a new database connection if there is none yet for the
    current application context.
    """
    if not hasattr(g, 'sqlite_db'):
        g.sqlite_db = connect_db()
    return g.sqlite_db


def init_db():
    db = get_db()

    y = input("Are you sure you want to DELETE ALL DATA and re-initialize the database? [y/n]")
    if y != 'y' and y != 'Y':
        print("Aborting.")
        return False

    # apply the schema
    with app.open_resource('schema.sql', mode='r') as f:
        db.cursor().executescript(f.read())

    db.commit()

    print(Fore.RED + "Database Initialized" + Style.RESET_ALL)
    return True


def load():
    db = get_db()

    # insert all the files from the file system
    sample_names = os.listdir("/var/www/html/grouping/samples")
    for sample_name in sample_names:
        if sample_name:  # check for empty string
            sample_url = SAMPLES_URL_PREFIX + sample_name
            try:
                db.execute('INSERT INTO samples (url, count) VALUES (?, ?) ', [sample_url, 0])
                print(Fore.BLUE, end='')
                print("Added", sample_url)
                print(Fore.RESET, end='')
            except sqlite3.IntegrityError:
                # skip this because the sample already exists!
                print(Fore.YELLOW, end='')
                print("Skipped", sample_url)
                print(Fore.RESET, end='')

    db.commit()

    return True


def dump_db(outfile_name):
    # for pretty terminal output
    init()

    db = get_db()

    if outfile_name:
        outfile = open(outfile_name, 'w')
    else:
        outfile = open(os.devnull, 'w')

    def print_samples_db():
        samples_cur = db.execute('SELECT url, count FROM samples ORDER BY count ASC')
        entries = samples_cur.fetchall()

        # figure out dimensions
        url_w = "100"
        count_w = "5"

        header_format = "{:<" + url_w + "." + url_w + "s} {:s}"
        header = header_format.format("URL", "count")
        w = len(header)
        row_format = "{:<" + url_w + "." + url_w + "s} {:<" + count_w + "d}"

        print(Fore.GREEN + "Dumping Database" + Style.RESET_ALL)

        print("=" * w)
        print(header)
        print("=" * w)
        for entry in entries:
            url = entry[0]
            url = url.strip(SAMPLES_URL_PREFIX)
            count = entry[1]
            print(row_format.format(url, count))
        print("=" * w)

    def print_response_db():
        responses_cur = db.execute('SELECT id, url, stamp, experiment_id, data FROM responses ORDER BY stamp DESC')
        entries = responses_cur.fetchall()

        json_out = []

        headers = OrderedDict()
        headers['id'] = 3
        headers['url'] = 20
        headers['stamp'] = 27
        headers['experiment_id'] = 13
        term_size = shutil.get_terminal_size((100, 20))
        total_width = term_size.columns
        headers['data'] = max(total_width - sum(headers.values()) - len(headers), 0)
        fmt = ""
        for k, w in headers.items():
            fmt += "{:<" + str(w) + "." + str(w) + "s} "
        fmt = fmt.strip(' ')
        header = fmt.format(*headers.keys())
        print("=" * total_width)
        print(header)
        for entry in entries:
            response = json.loads(entry[4])
            json_out.append({
                'id': entry[0],
                'url': entry[1],
                'stamp': str(entry[2]),
                'experiment_id': entry[3],
                'data': response
            })
            cols = [str(col) for col in entry]
            cols[1] = cols[1].strip(SAMPLES_URL_PREFIX)
            data = "["
            for d in response['final_response']:
                s = "%0.2f, " % d['timestamp']
                if len(data + s) > headers['data'] - 4:
                    data += "..., "
                    break
                data += s
            if len(data) == 1:
                cols[-1] = data + "]"
            else:
                cols[-1] = data[:-2] + "]"
            if len(cols[3]) > headers['experiment_id']:
                cols[3] = cols[3][0:headers['experiment_id'] - 3] + '...'
            print(fmt.format(*cols))
        print("=" * total_width)

        json.dump(json_out, outfile, indent=2)

    print_samples_db()
    print_response_db()


def remove_from_sample_db(sample, force=False):
    db = get_db()
    sample_url = SAMPLES_URL_PREFIX + sample
    try:
        check_count_cur = db.execute('SELECT count FROM samples WHERE url=?', [sample_url])
        sample_counts = check_count_cur.fetchone()
        if len(sample_counts) == 0:
            print(Fore.YELLOW, end='')
            print("Sample", sample_url, "does not exist.")
            print(Fore.YELLOW, end='')
            return

        count = sample_counts[0]
        if count > 0 and not force:
            print(Fore.YELLOW, end='')
            print("Sample", sample_url, "has", count, "responses, so you shouldn't delete it. This requires --force.")
            print(Fore.YELLOW, end='')
            return

        if not force:
            remove_cur = db.execute('DELETE FROM samples WHERE url=? AND count=0 ', [sample_url])
        else:
            remove_cur = db.execute('DELETE FROM samples WHERE url=?', [sample_url])

        if remove_cur.rowcount == 1:
            print(Fore.BLUE, end='')
            print("Removed", sample_url)
            print(Fore.RESET, end='')
        else:
            print(Fore.YELLOW, end='')
            print("Failed to remove", sample_url, ". Try again, this might be a race condition.")
            print(Fore.RESET, end='')
    except sqlite3.IntegrityError as e:
        print(Fore.RED, end='')
        print(e)
        print(Fore.RESET, end='')

    db.commit()


def sample_new_urls(entries, samples_per_participant):
    """ samples from a*x^a-1 """
    a = 10
    sample_indeces = []
    while True:
        idx = int(np.random.power(a) * entries.shape[0])
        if idx not in sample_indeces:
            sample_indeces.append(idx)
        if len(sample_indeces) == samples_per_participant:
            break
    sample_indeces = np.array(sample_indeces)
    return entries[sample_indeces]


@app.teardown_appcontext
def close_db(error):
    """Closes the database again at the end of the request."""
    if hasattr(g, 'sqlite_db'):
        g.sqlite_db.close()


@app.route('/responses', methods=['POST'])
def responses():
    db = get_db()
    req_data = request.get_json()
    samples = req_data['samples']
    ip_addr = request.remote_addr
    stamp = datetime.now()
    metadata = req_data['metadata']
    experiment_id = req_data['experiment_id']

    sample_responses = req_data['responses']
    for idx, data in enumerate(sample_responses):
        url = samples[idx]['url']
        # sort the final response by timestamps for sanity
        sorted_final_response = sorted(data['final_response'], key=lambda d: d['timestamp'])
        data['final_response'] = sorted_final_response
        db.execute(
            'INSERT INTO responses (url, ip_addr, stamp, experiment_id, metadata, data) VALUES (?, ?, ?, ?, ?, ?)',
            [url, ip_addr, stamp, experiment_id, json.dumps(metadata), json.dumps(data)])

    for sample in samples:
        db.execute('UPDATE samples SET count = count + 1 WHERE url= ?', [sample['url']])

    db.commit()

    # submit the answers to mechanical turk if necessary as well

    data = {'status': 'ok'}
    js = json.dumps(data)
    resp = Response(js, status=200, mimetype='application/json')
    return resp


@app.route('/survey', methods=['GET'])
def survey():
    samples_per_participant = int(request.args.get('samplesPerParticipant', DEFAULT_SAMPLES_PER_PARTICIPANT))
    assignment_id = request.args.get('assignmentId', "ASSIGNMENT_ID_NOT_AVAILABLE")
    experiment_id = request.args.get('experimentId', "EXPERIMENT_ID_NOT_AVAILABLE")
    href = "interface?experimentId={:s}&samplesPerParticipant={:d}&assignmentId={:s}".format(experiment_id,
                                                                                             samples_per_participant,
                                                                                             assignment_id)
    return render_template('survey.html', experimentId=experiment_id, next_href=href)


@app.route('/welcome', methods=['GET'])
def welcome():
    samples_per_participant = int(request.args.get('samplesPerParticipant', DEFAULT_SAMPLES_PER_PARTICIPANT))
    assignmentId = request.args.get('assignmentId', "ASSIGNMENT_ID_NOT_AVAILABLE")
    # lol this is such good code...
    random_numbers = [np.random.randint(0, 255) for _ in range(8)]
    experiment_id = "{:2x}::{:2x}::{:2x}::{:2x}::{:2x}::{:2x}::{:2x}::{:2x}".format(*random_numbers)
    href = "survey?experimentId={:s}&samplesPerParticipant={:d}&assignmentId={:s}".format(experiment_id,
                                                                                          samples_per_participant,
                                                                                          assignmentId)
    return render_template('welcome.html', next_href=href)


@app.route('/thankyou_mturk', methods=['GET'])
def thank_you_mturk():
    assignment_id = request.args.get('assignmentId', "ASSIGNMENT_ID_NOT_AVAILABLE")
    experiment_id = request.args.get('experimentId', "EXPERIMENT_ID_NOT_AVAILABLE")
    submit_url = "https://workersandbox.mturk.com/mturk/externalSubmit?assignmentId={:s}&experimentId={:s}".format(
        assignment_id, experiment_id)
    return render_template('thankyou_mturk.html', submit_url=submit_url)


@app.route('/thankyou', methods=['GET'])
def thank_you():
    assignment_id = request.args.get('assignmentId', "ASSIGNMENT_ID_NOT_AVAILABLE")
    return render_template('thankyou.html', assignmentId=assignment_id)


@app.route('/manage', methods=['POST'])
def manage_post():
    req_data = request.get_json()
    selected_samples = req_data['selected_samples']
    unselected_samples = req_data['unselected_samples']
    # set database contents to these selected samples
    additions = []
    skipped_additions = []
    removals = []
    skipped_removals = []
    db = get_db()

    # Add samples (skip duplicates)
    for sample_url in selected_samples:
        try:
            db.execute('INSERT INTO samples (url, count) VALUES (?, ?) ', [sample_url, 0])
            additions.append(sample_url)
        except sqlite3.IntegrityError:
            # skip this because the sample already exists!
            skipped_additions.append(sample_url)

    # Remove samples
    for sample_url in unselected_samples:
        try:
            db.execute('DELETE FROM samples WHERE url= ? AND count= 0 ', [sample_url])
            removals.append(sample_url)
        except sqlite3.IntegrityError:
            skipped_removals.append(sample_url)

    db.commit()
    return json.dumps({'status': 'success',
                       'additions': additions,
                       'skipped_additions': skipped_additions,
                       'removals': removals,
                       'skipped_removals': skipped_removals})


@app.route('/manage', methods=['GET'])
def manage_get():
    # get list of possible samples
    try:
        samples = []
        sample_names = os.listdir("/var/www/html/grouping/samples")
        for sample_name in sample_names:
            sample = {
                'url': SAMPLES_URL_PREFIX + sample_name,
                'name': sample_name
            }
            samples.append(sample)

        db = get_db()
        samples_cur = db.execute('SELECT url, count FROM samples ORDER BY count ASC')
        entries = samples_cur.fetchall()
        db_samples = []
        for entry in entries:
            db_samples.append({
                'url': entry[0],
                'count': int(entry[1])
            })

        return render_template('manage.html', samples=json.dumps(samples), db_samples=db_samples)
    except requests.exceptions.ProxyError:
        return render_template('error.html', reason="Failed to contact sever for list of samples.")


@app.route('/', methods=['GET'])
def root():
    assignmentId = request.args.get('assignmentId', "ASSIGNMENT_ID_NOT_AVAILABLE")
    return redirect(url_for('welcome', assignmentId=assignmentId))


@app.route('/interface', methods=['GET'])
def interface():
    db = get_db()
    cur = db.execute('SELECT url, count FROM samples ORDER BY count DESC')
    entries = np.array(cur.fetchall())
    samples_per_participant = int(request.args.get('samplesPerParticipant', DEFAULT_SAMPLES_PER_PARTICIPANT))
    assignment_id = request.args.get('assignmentId', "ASSIGNMENT_ID_NOT_AVAILABLE")
    experiment_id = request.args.get('experimentId', "EXPERIMENT_ID_NOT_AVAILABLE")

    if not assignment_id or assignment_id == "ASSIGNMENT_ID_NOT_AVAILABLE":
        href = "thankyou_mturk?assignmentId={:s}&experimentId={:s}".format(assignment_id, experiment_id)
    else:
        href = "thankyou?"

    if samples_per_participant <= 0 or samples_per_participant > 30:
        return render_template('error.html', reason='Number of samples per participant must be between 1 and 30')
    elif entries.shape[0] < samples_per_participant:
        return render_template('error.html', reason='Not samples available for response.')
    else:
        # randomly sample according to a power distribution--samples with fewer weights are more likely to be chosen
        urls_for_new_experiment = sample_new_urls(entries, samples_per_participant)
        samples = [{'url': e[0]} for e in urls_for_new_experiment]
        return render_template('interface.html', samples=json.dumps(samples), experiment_id=experiment_id,
                               next_href=href)


if __name__ == '__main__':
    app.run()
