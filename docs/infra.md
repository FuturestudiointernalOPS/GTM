# Infrastructure runbook — ProveItGo Creator Hunt

Owner: Intern 1 (infrastructure) · Last updated: 5 November 2026 (evening)

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
├── GTMTool/                 Python project (empty for now)
│   └── .venv/               project virtual environment (Python 3.12.3)
├── .hermes/                 Hermes Agent
│   ├── config.yaml          settings (model, Docker sandbox, checkpoints)
│   ├── .env                 secrets (DeepSeek API key) - never in Git
│   ├── hermes-agent/        program files
│   ├── proxy/               iron-proxy: proxy.yaml, ca.crt, mappings.json
│   └── logs/                agent.log, errors.log, egress-boot.log
└── (crontab)                @reboot: starts iron-proxy after boot
```

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
| Intern 2 | — | Pending |
| Intern 3 | — | Pending |

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

## 9. Next steps

- [x] Python and project virtual environment
- [x] Hermes Agent, Docker sandbox locked, iron-proxy with autostart
- [x] AI connection (DeepSeek) and sandbox test
- [ ] Repository skeleton: folders, `.gitignore`, `requirements.txt`, `.env.example`
- [ ] Secrets sharing decision (Bitwarden Families or free option)
- [ ] Telegram: Future Studio account (company phone number), bot, access limited to Henry, gateway as a service, reboot test
- [ ] SSH keys of Interns 2 and 3
- [ ] Weekly routine: `hermes update --backup`, then `hermes doctor`