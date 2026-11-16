# Sharing the demo from your own computer

One command gives the site, running on your Mac, a temporary public `https`
link that opens on any device. It is free and needs no account. The link works
while the command is running and the laptop is awake.

**Research and education demo. Not for diagnosis.**

## Start and stop

```
cd /Users/salemaker/Documents/code/senior_project_web
.venv/bin/python deploy/tunnel/share.py
```

After about half a minute it prints a box like this:

```
  Link:         https://some-random-words.trycloudflare.com
  User name:    demo
  Access code:  k7m2-xq9d
```

Give visitors the link, the user name and the access code. Their browser asks
for the two once.

- **Stop:** press Ctrl+C in that terminal. The link stops working at once and
  everything visitors uploaded is deleted.
- **It also stops by itself** after 3 hours. Use `--hours 1` for a shorter
  session (12 at most).
- **The link and the code are new every time** you start it.
- Keep the terminal window open, the lid open and the charger connected.

Options:

| Option | Effect |
|---|---|
| `--hours N` | stop automatically after N hours (default 3) |
| `--open` | no access code: anyone who has the link gets in |
| `--all-formats` | also accept `.mat`, `.h5`, TIFF and DICOM uploads |
| `--no-sandbox` | run without the sandbox (not recommended) |

One-time requirement: the tunnel tool, installed with `brew install cloudflared`.

## What protects your computer

No port on your Mac or your router is opened. The link exists because your Mac
makes an outgoing connection to Cloudflare, and Cloudflare passes visitors'
requests back along it. On top of that there are several independent layers,
so one failing does not expose the machine.

| Layer | What it does | What it stops |
|---|---|---|
| 1. Local-only server | The site listens on `127.0.0.1`, never on the network | Anyone on your Wi-Fi or the internet connecting to it directly |
| 2. Tunnel cage | The tunnel program may contact exactly one local port, read no personal files and start no programs | The tunnel being used to reach other things on your Mac |
| 3. Access code | A new random code per session; eight refusals ban an address for 15 minutes | Strangers who find the link; guessing the code |
| 4. Request firewall | Only GET, HEAD and POST; scanner paths such as `/.env` or `/wp-admin` get a bare "not found"; 120 requests a minute per address; 6 uploads a minute and 40 an hour per address | Automated scanners, flooding, misuse of the model as a free service |
| 5. Small upload surface | Only PNG and JPEG, 20 MB, 4096 by 4096 pixels | Attacks through complex file formats |
| 6. Server cage | The server cannot read your home folder (only this project's code and the model), cannot write outside `share_data/`, cannot reach the internet and cannot start other programs | A break-in through the site turning into access to your files |
| 7. Separate data | Its own database, upload folder and secret key; your local `.env`, database and uploads are unreadable from inside the cage | Visitors' data mixing with yours; your local secret leaking |
| 8. Browser rules | The pages may load only the site's own files; no inline scripts; no framing; search engines are told not to index | Script injection, click-jacking, the link ending up in search results |
| 9. Time limit and wipe | Stops after the set hours; uploads and the session database are deleted on stop | A forgotten open link; data left behind |

Layers 2 and 6 use the macOS sandbox. Each was tested with a small program
that tried to list the home folder, read `.env`, write into the code, open an
internet connection and start a shell: all five were blocked.

## What it does not protect against

- **People you give the code to.** They can upload images and run the model
  within the limits. They cannot see each other's results.
- **Cloudflare can see the traffic.** The `https` connection ends at
  Cloudflare, which forwards it through the tunnel. Do not upload real patient
  scans.
- **It is a demo link, not a service.** Cloudflare offers these quick tunnels
  for testing, without any guarantee, and the address changes every time.
- **The rest of your Mac.** This setup opens nothing, but it also does not fix
  what is already open. See the next section.
- **A sandbox is a strong fence, not a proof.** Apple marks the `sandbox-exec`
  tool as deprecated; it works on this macOS version and the launcher prints
  "Sandbox: on" when it is active. If it ever prints "Sandbox: OFF", stop and
  find out why before sharing.

## Turn on the macOS firewall (recommended, once)

The Mac's own firewall is currently off. It is not needed for the tunnel, but
it protects the laptop on shared Wi-Fi in general, which matters on the
networks where you would present.

1. Open **System Settings**, then **Network**, then **Firewall**, and switch it on.
2. Click **Options** and switch on **Enable stealth mode**.

Or in a terminal (asks for your password):

```
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setstealthmode on
```

Optional: "AirPlay Receiver" keeps two ports open to everyone on the same
network. If you do not use it, switch it off under **System Settings**,
**General**, **AirDrop & Handoff**.

## After a session

The launcher prints how many requests were served, how many the firewall
refused and how many addresses it banned. The logs of the last session stay in
`share_data/logs/` until the next start:

- `access.log`: every request, with the visitor's address
- `server.log`: firewall refusals and bans, rejected uploads, errors
- `tunnel.log`: the tunnel program's own messages

`share_data/` is git-ignored and never leaves your Mac.

## If something goes wrong

| What you see | What to do |
|---|---|
| A browser says the address cannot be found | The new address needs up to a minute. Wait and reload. |
| "the tunnel tool is not installed" | `brew install cloudflared` |
| "a sharing session is already running" | Stop the other one with Ctrl+C in its terminal |
| "This demo needs its access code" keeps coming back | The code is wrong, or it is from an earlier session |
| "Too many bad requests from your address" | That address was banned for 15 minutes after repeated refusals |
| The site says "No trained models are installed yet" | Copy a model into `model_store/` first (see the README) |
| The link stopped working | The laptop slept, the network changed or the time limit passed. Start again. |
