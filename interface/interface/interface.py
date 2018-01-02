import json
import os
import sqlite3

from colorama import init, Fore, Style
from flask import Flask, render_template, g, request, Response
from datetime import datetime

app = Flask(__name__)
app.config.from_object(__name__)

app.config.update(dict(
    DATABASE=os.path.join(app.root_path, 'interface.db'),
    SECRET_KEY='C796D37C6D491E8F0C6E9B83EED34C15C0F377F9F0F3CBB3216FBBF776DA6325',
    USERNAME='admin',
    PASSWORD='password'
))


@app.cli.command('dumpdb')
def dumpdb_command():
    """Dump the database."""
    dump_db()


@app.cli.command('load')
def initdb_command():
    """Loads new samples into the samples table."""
    success = load()

    if success:
        dump_db()


@app.cli.command('initdb')
def initdb_command():
    """Initializes the database."""
    success = init_db()

    if success:
        dump_db()


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

    load()

    db.commit()

    print(Fore.RED + "Database Initialized" + Style.RESET_ALL)
    return True


def load():
    db = get_db()

    # insert all the files from the file system
    samples_path = os.path.join(app.root_path, 'static', 'samples')
    for idx, sample_title in enumerate(os.listdir(samples_path)):
        sample = os.path.join(samples_path, sample_title)
        if os.path.isfile(sample):
            sample_url = "/static/samples/" + sample_title
            try:
                db.execute('INSERT INTO samples (url, title, count) VALUES (?, ?, ?) ',
                           [sample_url, sample_title, 0])
                print(Fore.BLUE, end='')
                print("Added", sample_title)
                print(Fore.RESET, end='')
            except sqlite3.IntegrityError:
                # skip this because the sample already exists!
                print(Fore.YELLOW, end='')
                print("Skipped", sample_title)
                print(Fore.RESET, end='')

    db.commit()

    return True


def dump_db():
    # for pretty terminal output
    init()

    db = get_db()
    samples_cur = db.execute('SELECT url, title, count FROM samples ORDER BY count ASC')
    entries = samples_cur.fetchall()

    def print_samples_db():
        # figure out dimensions
        title_w = 0
        for entry in entries:
            title = entry[1]
            title_w = max(len(title), title_w)

        header_format = "{:" + str(title_w + 2) + "s}"
        count_header = "Count"
        header = header_format.format("Title") + count_header
        w = len(header)
        row_format = "{:" + str(title_w + 2) + "s} {:<" + str(len(count_header)) + "d}"

        print(Fore.GREEN + "Dumping Database" + Style.RESET_ALL)

        print("=" * w)
        for entry in entries:
            title = entry[1]
            count = entry[2]
            print(row_format.format(title, count))
        print("=" * w)

    def print_response_db():
        responses_cur = db.execute('SELECT * FROM responses ORDER BY stamp DESC')
        entries = responses_cur.fetchall()

        fmt = "{:<3s}{:<20s}{:<20s}{:<30s}{:<90s}"
        header = fmt.format("id", "sample_id", "ip_addr", "stamp", "data")
        w = len(header)
        print("=" * w)
        print(header)
        for entry in entries:
            print(fmt.format(*[str(s) for s in entry]))
        print("=" * w)

    print_samples_db()
    print_response_db()


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
    # FIXME: test this
    # print(ip_addr)

    sample_responses = req_data['responses']
    for idx, data in enumerate(sample_responses):
        sample_title = samples[idx]['title']
        sorted_data = sorted(data)
        db.execute('INSERT INTO responses (sample_title, ip_addr, stamp, data) VALUES (?, ?, ?, ?)',
                   [sample_title, ip_addr, stamp, json.dumps(sorted_data)])

    for sample in samples:
        db.execute('UPDATE samples SET count = count + 1 WHERE title = ?', [sample['title']])

    db.commit()

    data = {'status': 'ok'}
    js = json.dumps(data)
    resp = Response(js, status=200, mimetype='application/json')
    return resp


@app.route('/thankyou.html', methods=['GET'])
def thank_you():
    return render_template('thankyou.html')


@app.route('/', methods=['GET'])
def index():
    db = get_db()
    cur = db.execute('SELECT title, url, count FROM samples ORDER BY count ASC')
    entries = cur.fetchall()
    samples_per_participant = 2
    samples = [{'title': e[0], 'url': e[1]} for e in entries[:samples_per_participant]]
    return render_template('index.html', samples=json.dumps(samples))


if __name__ == '__main__':
    app.run(host="0.0.0.0")
