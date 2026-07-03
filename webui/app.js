const prevContent = {};
let pollInterval = null;

function renderTextWithLinks(el, text) {
  if (prevContent[el.id] === text) return;
  prevContent[el.id] = text;
  el.innerHTML = '';
  const urlRe = /https?:[/][\S]+/g;
  let last = 0;
  let match;
  while ((match = urlRe.exec(text)) !== null) {
    if (match.index > last) {
      el.appendChild(document.createTextNode(text.slice(last, match.index)));
    }
    const a = document.createElement('a');
    a.href = match[0];
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = match[0];
    el.appendChild(a);
    last = urlRe.lastIndex;
  }
  if (last < text.length) {
    el.appendChild(document.createTextNode(text.slice(last)));
  }
}

async function fetchStatus() {
  try {
    const r = await fetch('/status');
    const data = await r.json();
    renderTextWithLinks(document.getElementById('status'), data.status || 'Unable to get status');
  } catch {
    renderTextWithLinks(document.getElementById('status'), 'Failed to fetch status');
  }
}

async function fetchResources() {
  try {
    const r = await fetch('/resources');
    const data = await r.json();
    renderTextWithLinks(document.getElementById('resources'), data.resources || 'Unable to get resources');
  } catch {
    renderTextWithLinks(document.getElementById('resources'), 'Failed to fetch resources');
  }
}

function startPolling(ms) {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(() => {
    fetchStatus();
    fetchResources();
  }, ms);
}

fetchStatus();
fetchResources();
startPolling(2000);

fetch('/config').then(r => r.json()).then(data => {
  document.getElementById('network').value = data.network || '';
}).catch(() => {});

document.getElementById('login-form').addEventListener('submit', async function(e) {
  e.preventDefault();
  const btn = document.getElementById('login-btn');
  const msg = document.getElementById('login-message');
  const network = document.getElementById('network').value;

  btn.disabled = true;
  btn.textContent = 'Logging in...';
  msg.textContent = '';
  msg.className = 'message';

  let ok = false;
  try {
    const r = await fetch('/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ network })
    });
    const data = await r.json();
    ok = data.ok;
  } catch {}

  if (ok) {
    msg.textContent = 'Login submitted. Status will update automatically...';
    msg.className = 'message info';
    setTimeout(() => { msg.textContent = ''; msg.className = 'message'; }, 5000);
    fetchStatus();
    fetchResources();
    startPolling(1000);
    setTimeout(() => startPolling(2000), 10000);
  } else {
    msg.textContent = 'Login request failed. Please try again.';
    msg.className = 'message error';
  }

  btn.disabled = false;
  btn.textContent = 'Login';
});
