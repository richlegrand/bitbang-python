"""Cookie/session test server on localhost:8080.
Use with bitbangproxy or BitBang Python adapter to test cookie handling.

Tests: login sets cookies, admin checks cookies, logout deletes cookies."""

from flask import Flask, request, make_response

app = Flask(__name__)

@app.route('/')
def index():
    session = request.cookies.get('session')
    user = request.cookies.get('user')
    if session:
        status = f'Logged in as <b>{user}</b> (session={session})'
        action = '<form action="logout" method="POST"><button>Logout</button></form>'
        admin = '<p><a href="admin">Go to admin</a></p>'
    else:
        status = 'Not logged in'
        action = '''<form action="login" method="POST">
            <input name="user" placeholder="username" value="alice">
            <button>Login</button>
        </form>'''
        admin = ''

    return f'''<!DOCTYPE html>
<html><body style="font-family: sans-serif; max-width: 500px; margin: 40px auto;">
<h1>Cookie Test</h1>
<p>{status}</p>
{action}
{admin}
<hr>
<h3>Cookie Debug</h3>
<pre>Cookie header: {request.headers.get('Cookie', '(none)')}</pre>
</body></html>'''

@app.route('/login', methods=['POST'])
def login():
    user = request.form.get('user', 'alice')
    resp = make_response(f'''<!DOCTYPE html>
<html><body style="font-family: sans-serif; max-width: 500px; margin: 40px auto;">
<h1>Logged in as {user}</h1>
<p><a href="/">Home</a> | <a href="admin">Admin</a></p>
</body></html>''')
    resp.set_cookie('session', 'abc123')
    resp.set_cookie('user', user)
    return resp

@app.route('/admin')
def admin():
    session = request.cookies.get('session')
    user = request.cookies.get('user')
    if session == 'abc123':
        return f'''<!DOCTYPE html>
<html><body style="font-family: sans-serif; max-width: 500px; margin: 40px auto;">
<h1>Admin Panel</h1>
<p>Welcome, {user}! Session: {session}</p>
<p><a href="/">Home</a></p>
<form action="logout" method="POST"><button>Logout</button></form>
</body></html>'''
    return f'''<!DOCTYPE html>
<html><body style="font-family: sans-serif; max-width: 500px; margin: 40px auto;">
<h1>Unauthorized</h1>
<p>No valid session cookie found.</p>
<p>Cookie header: <code>{request.headers.get('Cookie', '(none)')}</code></p>
<p><a href="/">Go to login</a></p>
</body></html>''', 401

@app.route('/logout', methods=['POST'])
def logout():
    resp = make_response(f'''<!DOCTYPE html>
<html><body style="font-family: sans-serif; max-width: 500px; margin: 40px auto;">
<h1>Logged out</h1>
<p><a href="/">Home</a></p>
</body></html>''')
    resp.set_cookie('session', '', max_age=0)
    resp.set_cookie('user', '', max_age=0)
    return resp


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
