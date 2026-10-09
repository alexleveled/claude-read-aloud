const vscode = require('vscode');
const fs = require('fs');
const os = require('os');
const path = require('path');
const net = require('net');
const { execFile } = require('child_process');

// Shared with the Read Aloud plugin (reader/home.py).
const HOME = process.env.CLAUDE_VOICE_HOME || path.join(os.homedir(), '.claude-voice');
const STATE = path.join(HOME, 'read-aloud');
const PID_FILE = path.join(STATE, 'reader.pid');
const INSTALL = path.join(STATE, 'install.json');
const DAEMON = path.join(STATE, 'daemon.json');

const INSTALL_HINT = 'Read Aloud needs the Claude Code plugin. In Claude Code, run: '
  + '/plugin marketplace add alexleveled/claude-plugins, then /plugin install read-aloud@alexleveled, '
  + 'then start a new Claude session once.';

function exists(p) {
  try { return !!p && fs.existsSync(p); } catch (e) { return false; }
}

function findUv(recorded) {
  const setting = vscode.workspace.getConfiguration('claudeReadAloud').get('uvPath');
  const exe = process.platform === 'win32' ? 'uv.exe' : 'uv';
  const candidates = [
    setting,
    recorded,
    path.join(os.homedir(), '.local', 'bin', exe),
    path.join(os.homedir(), '.cargo', 'bin', exe),
    '/opt/homebrew/bin/uv',
    '/usr/local/bin/uv',
  ];
  for (const c of candidates) if (exists(c)) return c;
  for (const dir of (process.env.PATH || '').split(path.delimiter)) {
    const c = path.join(dir, exe);
    if (exists(c)) return c;
  }
  return null;
}

// Where the reader lives: the plugin writes install.json from its SessionStart hook.
function locate() {
  let info = {};
  try { info = JSON.parse(fs.readFileSync(INSTALL, 'utf8')); } catch (e) { /* not recorded yet */ }
  const setting = vscode.workspace.getConfiguration('claudeReadAloud').get('readerScript');
  const reader = [setting, info.reader].find(exists);
  return { reader, uv: findUv(info.uv) };
}

// Talk straight to the warm reader when it's up: no process to start, so a read begins in
// well under a second. Resolves null when it isn't running.
function askDaemon(req, timeout) {
  return new Promise((resolve) => {
    let d;
    try { d = JSON.parse(fs.readFileSync(DAEMON, 'utf8')); } catch (e) { return resolve(null); }
    const sock = net.createConnection({ host: '127.0.0.1', port: d.port });
    let buf = '';
    const done = (v) => { sock.destroy(); resolve(v); };
    sock.setTimeout(timeout, () => done(null));
    sock.on('error', () => done(null));
    sock.on('connect', () => sock.write(JSON.stringify({ ...req, token: d.token }) + '\n'));
    sock.on('data', (chunk) => {
      buf += chunk.toString('utf8');
      if (buf.endsWith('\n')) {
        try { done(JSON.parse(buf)); } catch (e) { done(null); }
      }
    });
  });
}

// Reader command: warm reader first, then the plugin's script through uv (which starts it).
async function call(req, args, timeout, callback) {
  const resp = await askDaemon(req, timeout);
  if (resp) {
    if (req.cmd === 'sessions') return callback(null, JSON.stringify(resp.data || []), '');
    return callback(resp.ok ? null : new Error(resp.message), resp.message || '', '');
  }
  if (!run(args, timeout, callback)) callback(new Error('not installed'), '', '');
}

function run(args, timeout, callback) {
  const { reader, uv } = locate();
  if (!reader || !uv) {
    vscode.window.showWarningMessage(INSTALL_HINT, 'Copy install commands').then((choice) => {
      if (choice) {
        vscode.env.clipboard.writeText(
          '/plugin marketplace add alexleveled/claude-plugins\n/plugin install read-aloud@alexleveled');
      }
    });
    return false;
  }
  execFile(uv, ['run', '--quiet', '--script', reader, ...args], { windowsHide: true, timeout }, callback);
  return true;
}

function isReading() {
  try {
    const pid = parseInt(fs.readFileSync(PID_FILE, 'utf8').trim(), 10);
    if (!Number.isInteger(pid) || pid <= 0) return false;
    process.kill(pid, 0);  // signal 0 only checks that the process exists
    return true;
  } catch (e) {
    return false;
  }
}

function activate(context) {
  const item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  const setIdle = () => {
    item.text = '$(play) Read';
    item.tooltip = 'Read the last Claude reply aloud (Ctrl+Alt+R)';
    item.command = 'claudeReadAloud.read';
  };
  const setReading = () => {
    item.text = '$(debug-stop) Stop';
    item.tooltip = 'Stop reading (Ctrl+Alt+S)';
    item.command = 'claudeReadAloud.stop';
  };
  let busy = false;  // finding sessions or starting a read: leave the spinner alone
  setIdle();
  item.show();

  const timer = setInterval(() => {
    if (busy) return;
    if (isReading()) setReading(); else setIdle();
  }, 1000);

  const startRead = (args) => {
    item.text = '$(loading~spin) Reading...';
    const req = { cmd: 'read' };
    for (let i = 0; i < args.length; i += 2) req[args[i].replace(/^--/, '')] = args[i + 1];
    call(req, ['read', ...args], 60000, (error, stdout, stderr) => {
      busy = false;
      const out = String(stdout || '').trim();
      if (error) {
        vscode.window.showErrorMessage('Read Aloud: ' + (out || stderr || error.message));
        setIdle();
      } else {
        vscode.window.setStatusBarMessage(out, 5000);
      }
    });
  };

  context.subscriptions.push(
    item,
    { dispose: () => clearInterval(timer) },
    vscode.commands.registerCommand('claudeReadAloud.read', () => {
      const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.cwd();
      busy = true;
      item.text = '$(loading~spin) Finding sessions...';

      // More than one Claude session active recently in this folder: let the user pick.
      call({ cmd: 'sessions', cwd }, ['sessions', '--cwd', cwd], 30000, async (error, stdout) => {
        if (error && error.message === 'not installed') { busy = false; return setIdle(); }
        let sessions = [];
        try { sessions = error ? [] : JSON.parse(String(stdout)); } catch (e) { sessions = []; }
        if (sessions.length === 0) return startRead(['--cwd', cwd]);  // reader explains why
        if (sessions.length === 1) return startRead(['--transcript', sessions[0].transcript]);

        const ago = (s) => s < 60 ? 'just now' : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`;
        const pick = await vscode.window.showQuickPick(
          sessions.map((s) => ({
            label: `$(play) ${s.project}`,
            description: `${ago(s.age_seconds)}${s.title ? ' · ' + s.title : ''}`,
            detail: s.preview,
            transcript: s.transcript,
          })),
          { placeHolder: 'Which Claude session should I read?', matchOnDescription: true, matchOnDetail: true }
        );
        if (!pick) { busy = false; return setIdle(); }
        startRead(['--transcript', pick.transcript]);
      });
    }),
    vscode.commands.registerCommand('claudeReadAloud.stop', () => {
      askDaemon({ cmd: 'stop' }, 5000).then(() => {
        try { fs.unlinkSync(PID_FILE); } catch (e) { /* already gone */ }
        setIdle();
      });
    })
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
