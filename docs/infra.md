# Infrastructure runbook — ProveItGo Creator Hunt

Owner: Intern 1 (infrastructure) · Last updated: 9 November 2026

This file records how the server was built, step by step, so that someone new can rebuild it from this document alone. **It must never contain secrets** (passwords, API keys, private keys). Secrets live in Bitwarden.

---

## 0. What is on the server today

One server (`vmi3726974`), one shared Linux account (`hunter`). Every team member connects as `hunter` with their own SSH key.

**System level**

| Component | Role |
|---|---|
| Ubuntu (UTC clock) | Operating system |
| OpenSSH (keys only, root refused) | Entry point |
| ufw | Firewall: only SSH is allowed in |
| fail2ban | Bans repeated failed logins |
| unattended-upgrades | Daily automatic security updates |
| Docker | Runs the agent's sandbox containers |
| tmux | Keeps terminal sessions alive through disconnections |

**Inside `/home/hunter/`**

```
/home/hunter/
├── .ssh/authorized_keys     SSH public keys allowed to log in
├── GTMTool/                 Python project (to be replaced by a clone of the GTM repo)
│   ├── .venv/               project virtual environment (Python 3.12.3)
│   └── .env                 DEEPSEEK_API_KEY (chmod 600) - never in Git
├── backups/                 encrypted backups (*.tar.gz.age)
├── .hermes/                 Hermes Agent
│   ├── config.yaml          settings (model, Docker sandbox, checkpoints)
│   ├── .env                 secrets (DeepSeek API key) - never in Git
│   ├── hermes-agent/        program files
│   ├── proxy/               iron-proxy: proxy.yaml, ca.crt, mappings.json
│   └── logs/                agent.log, errors.log, egress-boot.log
└── (crontab)                @reboot: starts iron-proxy after boot
```

`~/.ssh/gtm_deploy` (read-only deploy key for the GitHub repo) is planned, not created yet.

**Docker images:** `nousresearch/hermes-sandbox:desktop` (4.4 GB on disk, 1.2 GB download), `hello-world`.

---

## 1. Server

| Item | Value |
|---|---|
| Provider | Contabo |
| Plan | Cloud VPS 4 (Core): 4 vCPU, 8 GB RAM, 100 GB SSD, 1 snapshot, 200 Mbit/s |
| Region | European Union |
| Operating system | Ubuntu LTS (confirm the exact version with `lsb_release -a`) |
| Term | 1 month, $6.60 a month, no setup fee |
| Auto Backup | Not taken (snapshot + our own encrypted backups instead) |
| Hostname | `vmi3726974` |
| IP address | `<SERVER_IP>` (stored in Bitwarden) |
| Account owner | Future Studio (paid with Henry's card) |
| Time zone | UTC |

## 2. Differences from the Bot setup tab

| Bot setup | What we did | Why |
|---|---|---|
| OVHcloud VPS, first user `ubuntu` | Contabo VPS, first user `root` | More RAM for the price; Contabo images start with root |
| Kimi K2.6 via OpenRouter | DeepSeek, for now | Team decision; the AI layer must stay interchangeable |
| Clock assumed to be UTC | Contabo default was `Europe/Berlin`, changed to UTC | The Monday run is scheduled at 06:00 UTC |
| OVHcloud KVM console | Contabo **VNC Control** and **Rescue System** | Same purpose: emergency access |

## 3. Access

| Account | SSH login | Notes |
|---|---|---|
| `root` | **Disabled** | Still exists; used through `sudo` and the Contabo console |
| `hunter` | Key only | Member of `sudo` and `docker` groups; runs the project |

**SSH keys installed on `hunter`:**

| Person | Key type | Status |
|---|---|---|
| Intern 1 | ed25519 | Installed |
| Abel (teammate) | ed25519 | Installed |
| Third intern | — | Pending |

Rule: **one key per person**, so a key can be removed without affecting the others.

**Secrets:** the root and hunter passwords are in Bitwarden. Never in chat, email or Git.

**Laptop SSH configuration** (`~/.ssh/config`, `chmod 600`):

```
Host proveitgo-hunter
    HostName <SERVER_IP>
    User hunter
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 30
    ServerAliveCountMax 10
```

`ServerAliveInterval` keeps the connection open when idle; without it, sessions froze after a few minutes. Connect with `ssh proveitgo-hunter`.

## 4. Setup steps performed

### 4.1 First login and root password

```bash
ssh root@<SERVER_IP>
```

The root password was then reset from the Contabo panel (**Reset credentials**) and stored in Bitwarden.

### 4.2 System update

```bash
apt update && apt -y upgrade
```

### 4.3 Create the hunter user

```bash
adduser hunter
usermod -aG sudo hunter
groups hunter        # must list: sudo
```

### 4.4 Install the SSH key (from the laptop)

```bash
ssh-copy-id hunter@<SERVER_IP>
ssh -i ~/.ssh/id_ed25519 hunter@<SERVER_IP>   # test
sudo whoami                                    # must answer: root
```

`ssh-copy-id` added two public keys (ed25519 and an older RSA key). The RSA key was removed to keep one key per person:

```bash
cp ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak
sed -i '/^ssh-rsa /d' ~/.ssh/authorized_keys
cat ~/.ssh/authorized_keys       # only the ssh-ed25519 line remains
rm ~/.ssh/authorized_keys.bak    # after a successful login test
```

### 4.5 Turn off password and root login

Only after the key login test passed, with a second session kept open:

```bash
printf "PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n" | sudo tee /etc/ssh/sshd_config.d/00-hardening.conf
sudo sshd -t                     # no output = no error
sudo systemctl restart ssh
```

### 4.6 Firewall

SSH is allowed **before** the firewall is turned on.

```bash
sudo ufw allow OpenSSH
sudo ufw --force enable
sudo ufw status                  # Status: active, OpenSSH ALLOW
```

### 4.7 fail2ban

```bash
sudo apt -y install fail2ban
sudo systemctl status fail2ban   # active (running)
```

### 4.8 Docker and tools

```bash
sudo apt -y install docker.io git curl xz-utils
sudo usermod -aG docker hunter
# log out and back in, then:
docker run --rm hello-world      # "Hello from Docker!"
```

### 4.9 Automatic security updates

```bash
sudo apt -y install unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades   # answer Yes
```

### 4.10 Time zone

```bash
timedatectl                              # was Europe/Berlin
sudo timedatectl set-timezone UTC
timedatectl                              # Time zone: UTC, synchronized: yes
```

### 4.11 Snapshot

Contabo panel → server menu → **Create Snapshot** → `serveur-securise-2026-11-05`.
The plan keeps one snapshot only: each new one replaces the previous one.

### 4.12 Python environment

```bash
python3 --version                          # 3.12.3
sudo apt -y install python3-venv python3-pip
mkdir ~/GTMTool && cd ~/GTMTool
python3 -m venv .venv
source .venv/bin/activate                  # prompt shows (.venv)
```

Re-activate in every new session: `cd ~/GTMTool && source .venv/bin/activate`. `.venv` is never committed; libraries go in `requirements.txt`.

### 4.13 Hermes Agent

Installed as hunter, never with sudo:

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh -o install-hermes.sh
less install-hermes.sh                     # read before running
bash install-hermes.sh
source ~/.bashrc
hermes --version && hermes doctor
```

Wizard answers:

| Question | Answer |
|---|---|
| Setup type | Full setup |
| Provider | DeepSeek, base URL `https://api.deepseek.com/v1` |
| Model | `deepseek-v4-flash` (fixed version; switch with `hermes model`) |
| Reasoning effort | medium |
| Terminal backend | Docker/Podman |
| Egress firewall for sandboxes | Yes |
| Messaging platforms | None for now (Telegram later) |
| Start gateway / start on boot | No (done with the Telegram step) |

The installer enabled systemd **linger** for hunter, so hunter's services keep running after logout.

**Sandbox settings checked in `~/.hermes/config.yaml`:**

```yaml
terminal:
  backend: "docker"
  docker_mount_cwd_to_workspace: false
  client_env_passthrough: []
  docker_forward_env: []      # added by hand: no secrets enter the sandbox
checkpoints:                  # added by hand at the end of the file
  enabled: true
```

`hermes doctor` after the edit: configuration all green, no deprecated keys.

### 4.14 Docker permissions for Hermes

After `usermod -aG docker hunter`, background processes started earlier (systemd user manager, kept alive by linger) still had the old groups, so Hermes got `permission denied` on `/var/run/docker.sock`. Fix: `sudo reboot`, then `id` must list `docker`.

### 4.15 Egress proxy (iron-proxy)

The egress firewall needs iron-proxy. The sandbox only receives an opaque proxy token; the proxy swaps it for the real DeepSeek key outside the sandbox.

```bash
hermes egress setup        # installs iron-proxy 0.39.0, CA cert, tokens, proxy.yaml
hermes egress start
hermes egress status       # Listening yes, Docker enforce yes
```

`hermes egress` has **no autostart**. Added to hunter's crontab (`crontab -e`):

```
@reboot sleep 30 && /home/hunter/.local/bin/hermes egress start >> /home/hunter/.hermes/logs/egress-boot.log 2>&1
```

The 30 s delay lets Docker start first (on Linux the proxy binds to the Docker bridge). Tested with a reboot: proxy back up on its own.

### 4.16 Sandbox image

The first sandbox start timed out (image pull longer than 120 s, retried 3 times, about 10 minutes). Pre-pulled by hand:

```bash
docker pull nousresearch/hermes-sandbox:desktop
```

### 4.17 tmux

```bash
sudo apt -y install tmux
tmux new -s travail          # start a session
# Ctrl+B then D             # detach, session keeps running
tmux attach -t travail       # come back after a disconnection
```

Sessions do not survive a server reboot.

### 4.18 First DeepSeek call from Python

```bash
cd ~/GTMTool && source .venv/bin/activate
pip install openai python-dotenv
nano .env                      # DEEPSEEK_API_KEY=...  (no quotes, no spaces)
chmod 600 .env
python test_deepseek.py        # "Yes, I'm working and ready to help." - 93 tokens
```

DeepSeek is OpenAI-compatible: the `openai` library is used with `base_url="https://api.deepseek.com/v1"` and `model="deepseek-v4-flash"`. Switching provider later means changing the base URL and model name, which the `AIProvider` layer will isolate. The test script will become `ai/deepseek.py`.

Common mistake: a new SSH session starts in `~`, not `~/GTMTool`. Always `cd ~/GTMTool && source .venv/bin/activate` first (prompt shows `(.venv)`).

### 4.19 Encrypted backup and restore test

What is backed up: `~/.hermes` (without the 2.9 GB of reinstallable files), `GTMTool/.env`, `.ssh/authorized_keys` and the crontab. Archive size: about 1.6 MB.

```bash
sudo apt -y install age
mkdir -p ~/backups
crontab -l > ~/crontab-backup.txt
tar -czf ~/backups/hermes-$(date +%F).tar.gz \
  --exclude='.hermes/hermes-agent' --exclude='.hermes/tools' \
  --exclude='.hermes/cache' --exclude='.hermes/installs' \
  --exclude='.hermes/models_dev_cache.json' \
  -C ~ .hermes GTMTool/.env .ssh/authorized_keys crontab-backup.txt
age -p -o ~/backups/hermes-$(date +%F).tar.gz.age ~/backups/hermes-$(date +%F).tar.gz
rm ~/backups/hermes-$(date +%F).tar.gz ~/crontab-backup.txt     # never keep the plain archive
chmod 600 ~/backups/*.age
```

The age passphrase is in Bitwarden ("Sauvegarde Hermes - phrase age"). Without it the backup cannot be read.

**Off-server copy** (from the laptop, temporary until an online storage is chosen):

```bash
mkdir -p ~/Backups/proveitgo
scp proveitgo-hunter:~/backups/hermes-YYYY-MM-DD.tar.gz.age ~/Backups/proveitgo/
```

**Restore test** (done on the laptop, 9 November 2026, passed):

```bash
mkdir -p /tmp/restore-test && cd /tmp/restore-test
age -d -o hermes.tar.gz ~/Backups/proveitgo/hermes-YYYY-MM-DD.tar.gz.age
tar -tzf hermes.tar.gz | grep -E '\.hermes/\.env$|GTMTool/\.env|crontab-backup|authorized_keys'   # 4 lines
tar -xzf hermes.tar.gz && tail -n 1 crontab-backup.txt                                             # the @reboot line
cd ~ && rm -rf /tmp/restore-test     # decrypted files contain keys in clear
```

To restore on a rebuilt server: reinstall Hermes, extract the archive into `/home/hunter`, then `crontab crontab-backup.txt`.

Current limits: manual (to redo every Sunday with the snapshot), and the off-site copy is a laptop. To automate once Henry picks a storage (for example Backblaze B2).

### 4.20 Dangerous commands in scheduled runs

Added at the end of `~/.hermes/config.yaml`:

```yaml
approvals:
  mode: manual       # interactive sessions ask before a dangerous command
  cron_mode: deny    # scheduled runs block dangerous commands
```

Checks: `grep -n "command_allowlist" ~/.hermes/config.yaml` returns nothing (no permanent allowlist), and `hermes doctor` stays green.

Notes:
- With the Docker backend, Hermes skips these checks because the container is the security boundary; `cron_mode: deny` is a second safety net if the backend ever changes.
- Never answer **always** to an approval prompt: permanent allowlist entries are checked before `cron_mode: deny` (reported in Hermes issue #60505).
- Never use `--yolo`.

### 4.21 Housekeeping

- Empty files named with 6 digits appeared in `~` after Hermes log lines were pasted into the terminal (`->` was read as a redirection). Removed with `find ~ -maxdepth 1 -type f -regextype egrep -regex '.*/[0-9]{6}' -empty -delete`. Rule: paste logs into chat, never into the terminal.
- `~/.hermes/config.yaml.save` (nano emergency save after a disconnection) and `install-hermes.sh` removed.
- Snapshot replaced by `hermes-proxy-ok-2026-11-05` (the plan keeps one snapshot: delete the old one first, only snapshot a known-good state).

## 4b. Code workflow (GitHub)

- Repository: `git@github.com:FuturestudiointernalOPS/GTM.git` (remote switched from HTTPS to SSH).
- `main` holds `.gitignore` and the project skeleton from Henry's plan (empty folders kept with `.gitkeep`). The skeleton was first created on the server, then copied to the repo with `rsync` (excluding `.venv`, `.env`, `__pycache__`).
- **Code is written on laptops, never on the server.** Each person works on a branch and opens a pull request; another intern reviews before merging into `main`.
- The server only pulls validated code (`git pull`), through a read-only deploy key (to be added by a repo admin in Settings, Deploy keys).
- Branch names: `intern1/<task>` (for example `intern1/ai-layer`, `intern1/config`, `intern1/docs-infra`). One task per branch, created from an up-to-date `main` (`git checkout main && git pull`). A branch that depends on another unmerged branch is created from it, and its pull request uses that branch as base.

## 4c. AI layer (code, on laptops)

Open pull requests: `intern1/ai-layer`, then `intern1/config` (based on `intern1/ai-layer`).

| File | Role |
|---|---|
| `ai/provider.py` | `AIProvider` contract: each provider only implements `chat(system, user)`; `analyze_creator`, `analyze_buyer` and `generate_outreach` are shared, load their prompt from `ai/prompts/<name>.md` and parse a JSON answer |
| `ai/deepseek.py` | `DeepSeekProvider`: OpenAI-compatible client, model from `.env` (default `deepseek-v4-flash`), keeps `last_usage` (tokens) for cost tracking |
| `ai/prompts/analyze_creator.md` | Provisional prompt for technical tests; the real criteria come from Intern 2 |
| `ai/__init__.py` | `get_ai_provider()` returns the provider named in `AI_PROVIDER`; unknown names stop with a clear error |
| `config/environment.py` | Loads `.env` once; `require()` stops with "Missing setting: NAME", `optional()` returns a default |
| `config/settings.py` | `AI_PROVIDER` (default `deepseek`) and `AI_MODEL` (empty = provider default) |
| `.env.example` | List of settings without values (copy to `.env`) |
| `tests/manual_check_ai.py` | Sends a fake Russian gaming creator through `get_ai_provider()` |

**Switching AI** needs no code change in the workflows: set `AI_PROVIDER` and `AI_MODEL` in `.env`. Adding a provider (for example OpenRouter/Kimi) means writing `ai/openrouter.py` with its `chat()` and adding it to `get_ai_provider()`.

**Run the manual check on a laptop** (repo root, venv on, `.env` with `DEEPSEEK_API_KEY`):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install openai python-dotenv
PYTHONPATH=. python tests/manual_check_ai.py
```

## 5. Verification tests

| Test | Command (from the laptop) | Expected | Result |
|---|---|---|---|
| Key login works | `ssh proveitgo-hunter` | Logged in as hunter | ✓ |
| Root login refused | `ssh root@<SERVER_IP>` | `Permission denied (publickey)` | ✓ |
| Password login refused | `ssh -o PubkeyAuthentication=no hunter@<SERVER_IP>` | `Permission denied (publickey)` | ✓ |
| sudo works | `sudo whoami` (on the server) | `root` | ✓ |
| Firewall on | `sudo ufw status` | active, OpenSSH only | ✓ |
| fail2ban on | `sudo systemctl status fail2ban` | active (running) | ✓ |
| Docker works | `docker run --rm hello-world` | Hello from Docker! | ✓ |
| Clock | `timedatectl` | UTC, synchronized | ✓ |
| Hermes health | `hermes doctor` | Config green, DeepSeek reachable, Docker running | ✓ |
| Sandbox | `hermes chat -q "Run uname -n and whoami in your terminal and tell me the output."` | Random container hostname (not `vmi3726974`), root inside the container | ✓ (26 s) |
| Proxy after reboot | `hermes egress status` | Listening yes | ✓ |
| DeepSeek from Python | `python test_deepseek.py` (in `~/GTMTool`, venv on) | Answer + token count | ✓ |
| Backup restore | Decrypt and extract on the laptop | 4 key files present, crontab line intact | ✓ |
| Cron safety | `tail -n 4 ~/.hermes/config.yaml`, `hermes doctor` | `cron_mode: deny`, config green | ✓ |
| Teammate access | `ssh hunter@<SERVER_IP>` from Abel's laptop | Logged in as hunter | ✓ |
| AI layer | `PYTHONPATH=. python tests/manual_check_ai.py` (laptop) | `DeepSeekProvider`, `{'is_gaming': True, 'language': 'ru', ...}`, about 290 tokens | ✓ |
| Unknown provider | `AI_PROVIDER=inconnu PYTHONPATH=. python tests/manual_check_ai.py` | `ValueError: Unknown AI_PROVIDER: 'inconnu'` | ✓ |

## 6. Adding a team member's SSH key

1. The person sends their **public** key only (the `.pub` file, one line starting with `ssh-ed25519`).
2. On the server, as hunter, add it on a new line:
   ```bash
   nano ~/.ssh/authorized_keys
   ```
3. The person tests `ssh hunter@<SERVER_IP>`.
4. Record it in the table in section 3.

To remove someone: delete their line from `~/.ssh/authorized_keys`.

## 7. Emergency access

| Problem | What to do |
|---|---|
| Locked out of SSH | Contabo panel → **VNC Control** (log in as root with the Bitwarden password), fix the key or the hardening file |
| Server will not boot | Contabo panel → **Rescue System** |
| Root password lost | Contabo panel → **Reset credentials** (no data loss) |
| Last resort | Restore the snapshot, or **Reinstall** (erases everything) |

After a reinstall, SSH warns `REMOTE HOST IDENTIFICATION HAS CHANGED`. Clear the old fingerprint on the laptop with `ssh-keygen -R <SERVER_IP>`. If this warning appears **without** a reinstall, stop and investigate.

**Never click "Cancel"** in the server menu: it ends the subscription.

## 8. Issues met and fixes

| Issue | Cause | Fix |
|---|---|---|
| Could not log in after changing the root password | Password replaced in Bitwarden before being changed on the server | Contabo **Reset credentials**. Rule: change on the server first, then save |
| `Connection refused` right after the reset | Server rebooting | Waited a few minutes |
| Terminal froze, typing not shown | SSH session dropped when idle | `ServerAliveInterval 30` in `~/.ssh/config` |
| `Could not resolve hostname` | Alias typed on the server instead of the laptop | Aliases only exist on the laptop; check the prompt first |
| `Timeout, server not responding` | Unstable internet (VPN) | `ServerAliveCountMax 10` in `~/.ssh/config`, work inside tmux; `uptime` confirmed the server had not crashed |
| Hermes: Docker `permission denied` | Old background processes without the docker group | `sudo reboot` |
| `proxy.enabled is true but iron-proxy is not configured` | Egress firewall enabled in the wizard, proxy never set up | `hermes egress setup` then `hermes egress start` |
| Sandbox start timeout | 1.2 GB image pulled on first use | `docker pull nousresearch/hermes-sandbox:desktop` |
| Proxy down after reboot | No autostart in `hermes egress` | `@reboot` line in hunter's crontab |
| `ModuleNotFoundError: dotenv` | Script run from `~` without the venv | `cd ~/GTMTool && source .venv/bin/activate` |
| `scp`/`ssh` alias not found | Command typed on the server | Run laptop commands in a laptop terminal (`aichath@`) |
| Snapshot refused | Plan allows one snapshot | Delete the old snapshot, then create the new one |

## 9. Next steps

- [x] Python environment, Hermes, Docker sandbox, iron-proxy with autostart
- [x] DeepSeek from Hermes and from Python
- [x] Repository skeleton on GitHub
- [x] Encrypted backup with a restore test (manual for now)
- [x] Dangerous commands denied in scheduled runs
- [x] Abel's SSH key
- [ ] SSH key of the third intern
- [ ] Read-only deploy key on GitHub, then clone the repo into `~/GTMTool` (move `.env`, recreate `.venv`)
- [ ] Telegram: Future Studio account (company phone number), bot, access limited to Henry, gateway as a service, reboot test
- [ ] Decisions from Henry: DeepSeek instead of OpenRouter/Kimi, secrets sharing, off-site backup storage
- [x] AI layer and central settings (pull requests `intern1/ai-layer` and `intern1/config`, waiting for review)
- [ ] `requirements.txt` (for now: `openai`, `python-dotenv`)
- [ ] Weekly routine (Sunday): `hermes update --backup`, `hermes doctor`, backup + off-site copy, snapshot