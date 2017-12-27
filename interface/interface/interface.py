#!/usr/bin/env python3
import os
import random
from colorama import init, Fore, Style
from flask import Flask, render_template, url_for, g
import sqlite3
import json

app = Flask(__name__)
app.config.from_object(__name__)

app.config.update(dict(
    DATABASE=os.path.join(app.root_path, 'interface.db'),
    SECRET_KEY='C796D37C6D491E8F0C6E9B83EED34C15C0F377F9F0F3CBB3216FBBF776DA6325',
    USERNAME='admin',
    PASSWORD='password'
))


# app.config.from_envvar('ENV_SETTINGS', silent=True)


@app.cli.command('dumpdb')
def dumpdb_command():
    """Dump the database."""
    dump_db()


@app.cli.command('initdb')
def initdb_command():
    """Initializes the database."""
    init_db()
    print('Initialized the database.')
    dump_db()


def init_db():
    db = get_db()

    # apply the schema
    with app.open_resource('schema.sql', mode='r') as f:
        db.cursor().executescript(f.read())

    # insert all the files from the file system
    samples_path = os.path.join(app.root_path, 'static', 'samples')
    for sample_name in os.listdir(samples_path):
        sample = os.path.join(samples_path, sample_name)
        if os.path.isfile(sample):
            sample_url = "/static/samples/" + sample_name
            db.execute('insert into samples (url, title, response_count) values (?, ?, ?)',
                       [sample_url, sample_name, 0])
    db.commit()


def dump_db():
    # for pretty terminal output
    init()

    db = get_db()
    cur = db.execute('SELECT url, title, response_count FROM samples ORDER BY response_count ASC')
    entries = cur.fetchall()

    # figure out dimensions
    title_w = 0
    for entry in entries:
        title = entry[1]
        title_w = max(len(title), title_w)

    header_format = "{:" + str(title_w + 2) + "s}"
    response_count_header = "Response Count"
    header = header_format.format("Title") + response_count_header
    w = len(header)
    row_format = "{:" + str(title_w + 2) + "s} {:<" + str(len(response_count_header)) + "d}"

    print(Fore.GREEN + "Dumping Database" + Style.RESET_ALL)
    print("=" * w)
    print(header)
    for entry in entries:
        title = entry[1]
        response_count = entry[2]
        print(row_format.format(title, response_count))
    print("=" * w)


def connect_db():
    """Connects to the specific database."""
    rv = sqlite3.connect(app.config['DATABASE'])
    rv.row_factory = sqlite3.Row
    return rv


def get_db():
    """Opens a new database connection if there is none yet for the
    current application context.
    """
    if not hasattr(g, 'sqlite_db'):
        g.sqlite_db = connect_db()
    return g.sqlite_db


@app.teardown_appcontext
def close_db(error):
    """Closes the database again at the end of the request."""
    if hasattr(g, 'sqlite_db'):
        g.sqlite_db.close()


@app.route('/thankyou.html', methods=['GET'])
def thankyou():
    return render_template('thankyou.html')


@app.route('/', methods=['GET'])
def index():
    db = get_db()
    cur = db.execute('SELECT url, title, response_count FROM samples ORDER BY response_count ASC')
    entries = cur.fetchall()
    samples = [{'url': e[0], 'title': e[1]} for e in entries]
    print(samples)
    return render_template('index.html', samples=json.dumps(samples))


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')