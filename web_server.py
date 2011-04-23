from flask import Flask, request, render_template, redirect, url_for, jsonify, send_file
from time import time, sleep
from functools import wraps
import sys
import uuid
import zmq
from ip_receiver import IPReceiver

app = Flask(__name__)

# is it safe to have global variables here?
db=None
fs=None
xreq=None
messages=[]

def print_exception(f):
    """
    This decorator prints any exceptions that occur to the webbrowser.  This printing works even for uwsgi and nginx.
    """
    import traceback
    @wraps(f)
    def wrapper(*args, **kwds):
        try:
            return f(*args, **kwds)
        except:
            return "<pre>%s</pre>"%traceback.format_exc()
    return wrapper

def get_db(f):
    """
    This decorator gets the database and passes it into the function as the first argument.
    """
    import misc, sys
    @wraps(f)
    def wrapper(*args, **kwds):
        global db
        global fs
        if db is None or fs is None:
            db,fs=misc.select_db(sys.argv)
        args = (db,fs) + args
        return f(*args, **kwds)
    return wrapper

@app.route("/")
def root():
    return render_template('ipython_root.html' if 'ipython' in sys.argv else 'root.html')

@app.route("/eval")
@get_db
def evaluate(db,fs):
    computation_id=db.create_cell(request.values['commands'])
    return jsonify(computation_id=computation_id)

@app.route("/answers")
@print_exception
@get_db
def answers(db,fs):
    results = db.get_evaluated_cells()
    return render_template('answers.html', results=results)


@app.route("/output_poll")
@print_exception
@get_db
def output_poll(db,fs):
    """
    Return the output of a computation id (passed in the request)

    If a computation id has output, then return to browser. If no
    output is entered, then return nothing.
    """
    computation_id=request.values['computation_id']
    sequence=int(request.values.get('sequence',0))
    results = db.get_messages(id=computation_id,sequence=sequence)
    print "Retrieved messages", results
    if results is not None and len(results)>0:
        return jsonify(content=results)
    return jsonify([])

@app.route("/output_long_poll")
@print_exception
@get_db
def output_long_poll(db,fs):
    """
    Implements long-polling to return answers.

    If a computation id has output, then return to browser. Otherwise,
    poll the database periodically to check to see if the computation id
    is done.  Return after a certain number of seconds whether or not
    it is done.

    This currently blocks (calls sleep), so is not very useful.
    """
    default_timeout=2 #seconds
    poll_interval=.1 #seconds
    end_time=float(request.values.get('timeout', default_timeout))+time()
    computation_id=request.values['computation_id']
    while time()<end_time:
        results = db.get_evaluated_cells(id=computation_id)
        if results is not None and len(results)>0:
            return jsonify({'output':results['output']})
        sleep(poll_interval)
    return jsonify([])

from flask import Response
import mimetypes
@app.route("/files/<cell_id>/<filename>")
@get_db
def cellFile(db,fs,cell_id,filename):
    """Returns a file generated by a cell from the filesystem."""
    # We can't use send_file because that will try to access the file
    # on the local filesystem (see the code to send_file).
    # So we have to do the work of send_file ourselves.
    #return send_file(fs.get_file(cell_id,filename), attachment_filename=filename)

    mimetype=mimetypes.guess_type(filename)[0]
    if mimetype is None:
        mimetype = 'application/octet-stream'
    return Response(fs.get_file(cell_id, filename), content_type=mimetype)

@app.route("/complete")
@get_db
def tabComplete(db,fs):
    global xreq
    if xreq==None:
        xreq=IPReceiver(zmq.XREQ,db.get_ipython_port("xreq"))
    header={"msg_id":str(uuid.uuid4())}
    code=request.values["code"]
    xreq.socket.send_json({"header":header, "msg_type":"complete_request", "content": { \
                "text":"", "line":code, "block":code, "cursor_pos":request.values["pos"]}})
    return jsonify({"completions":xreq.getMessages(header,True)[0]["content"]["matches"]})

if __name__ == "__main__":
    app.run(debug=True)
