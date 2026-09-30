# Maintaining the GitHub project

This guide covers:

1. [Putting the project on GitHub (first time)](#1-put-the-project-on-github-first-time)
2. [Publishing a release for colleagues](#2-publish-a-release-for-colleagues)
3. [Continuing on another computer (e.g. a Mac)](#3-continue-on-another-computer-eg-a-mac)
4. [Everyday changes](#4-everyday-changes)
5. [Making the next release](#5-making-the-next-release)

What goes to GitHub is the code, the documentation and the example plans. **Not** included
(see `.gitignore`):
- the `output` folder, which holds your researches, drafts, settings and exchange rates;
- the Python environment `.venv`;
- caches and log files.

Your data therefore never ends up on GitHub, and every colleague keeps their own.

---

## 1. Put the project on GitHub (first time)

### 1a. Create an empty repository on GitHub

1. Sign in at <https://github.com>. Use your company's GitHub organisation if there is one;
   check with IT if you are not sure where internal code may go.
2. Click **New repository**.
3. Name it, e.g. `price_lens`, and choose **Private**.
4. Do **not** tick "Add a README", ".gitignore" or "license". The project already has them.
5. Click **Create repository**, and keep the page open: it shows the repository address,
   e.g. `https://github.com/adhitchandy/price_lens.git`.

### 1b. Upload from the Windows computer

Use **one** of these two ways.

**Option A: GitHub Desktop.** Easiest, and needs no administrator rights.

1. Install GitHub Desktop from <https://desktop.github.com> and sign in.
2. **File → Add local repository…** and choose the `price_lens` folder (the one with
   `README.md` in it). When it says *"This directory does not appear to be a Git repository"*,
   click **create a repository**, then **Create repository**. Leave "Git ignore" at *None*
   and "License" at *None*, because the project has its own files.
3. On the left, check the list of files. There must be **no** `output/…` or `.venv/…` files.
4. Bottom left: summary `Price Lens 1.0.0`, then **Commit to main**.
5. **Publish repository** (top bar). Untick "Keep this code private" only if it really may be
   public, choose your organisation if needed, then **Publish**.

**Option B: the command line.** Needs Git for Windows from <https://git-scm.com/download/win>.

Open the project folder in Explorer, click the address bar, type `cmd` and press Return. In
the black window:

```bat
git config --global user.name "Your Name"
git config --global user.email "you@company.com"

git init -b main
git add .
git update-index --chmod=+x setup_mac.command start_new_app.command start_app.command
git status
```

`git status` lists what will be uploaded. There must be no `output/` and no `.venv/` in it.
Then:

```bat
git commit -m "Price Lens 1.0.0"
git remote add origin https://github.com/adhitchandy/price_lens.git
git push -u origin main
```

The first push opens a browser window to sign in to GitHub.

The `update-index --chmod=+x` line marks the Mac start files as runnable. With GitHub
Desktop that is not possible; do it once from the Mac instead (see 3c).

### 1c. Check

Open the repository page on GitHub:
- The README is shown with the screenshot.
- There is no `output` folder, and `docs/`, `src/`, `tests/` are there.

---

## 2. Publish a release for colleagues

A release is a fixed version colleagues can download as a zip, without needing git.

1. On the repository page: **Releases** (right-hand side) → **Draft a new release**.
2. **Choose a tag** → type `v1.0.0` → **Create new tag: v1.0.0 on publish**. The target is `main`.
3. **Release title**: `Price Lens 1.0.0`.
4. **Description**: copy the `1.0.0` section from [CHANGELOG.md](../CHANGELOG.md).
5. **Publish release**.

GitHub attaches **Source code (zip)** automatically. That zip is what colleagues download;
the README tells them what to do next. To give colleagues access to a private repository:
**Settings → Collaborators and teams → Add people** (or add a team of your organisation).

---

## 3. Continue on another computer (e.g. a Mac)

The cleanest way is to **download the project fresh from GitHub and bring only your data
along**. Copying the whole folder also works (see 3d), but a fresh copy avoids problems with
line endings, file permissions and OneDrive.

### Before you lose access to the Windows computer

- [ ] Everything is committed and pushed. GitHub Desktop shows *"No local changes"*, or
      `git status` says *"nothing to commit, working tree clean"* and `git push` says
      *"Everything up-to-date"*.
- [ ] Your **`output`** folder is copied somewhere you can reach from the Mac (USB stick,
      OneDrive, …). It is **not** on GitHub.
- [ ] Optional: note your own exchange rates and default settings. They are inside `output`
      too, so the copy above already includes them.

### 3a. Set up the Mac

1. Install **Python** 3.10+ from <https://www.python.org/downloads/macos/> and
   **Firefox** from <https://www.mozilla.org/firefox/>.
2. Install **git**. Open Terminal and type `git --version`. If macOS offers to install the
   "command line developer tools", accept.
3. Sign in to GitHub. Either install **GitHub Desktop for Mac** (<https://desktop.github.com>)
   and sign in, or use the GitHub command line (`brew install gh`, then `gh auth login`).

### 3b. Download the project

**GitHub Desktop:** *File → Clone repository…* → pick `price_lens` → choose a
local folder such as `~/Projects` (**not** inside OneDrive or iCloud Drive) → **Clone**.

**Terminal:**

```bash
mkdir -p ~/Projects && cd ~/Projects
git clone https://github.com/adhitchandy/price_lens.git
cd price_lens
```

Then:

1. Copy your **`output`** folder into `~/Projects/price_lens/`.
2. Double-click **`setup_mac.command`**. If macOS refuses to open it, see the README section
   *Install on a Mac*.
3. Double-click **`start_new_app.command`**. Your researches from Windows are all there.

### 3c. One-time: make the Mac start files runnable in git

Only needed if the first upload was made with GitHub Desktop on Windows. In Terminal, inside
the project folder:

```bash
git ls-files -s '*.command'
```

If the lines start with `100644`, run:

```bash
git update-index --chmod=+x setup_mac.command start_new_app.command start_app.command
git commit -m "Make the Mac start files runnable"
git push
```

After that, they start with `100755`, and colleagues on a Mac can double-click them straight
from the release zip.

### 3d. If you copied the whole folder instead

If you copied the Windows folder (including the hidden `.git` folder) to the Mac:

1. In Terminal, inside the folder, run `git config core.fileMode false`. Files copied from
   Windows often come with different permissions, and git would otherwise report every file as
   changed.
2. Run `git status`. If it still lists files you did not change, they are line-ending
   differences. `git add --renormalize . && git commit -m "Normalise line endings"` settles it
   once.
3. Double-click `setup_mac.command`. It notices the Windows `.venv` and replaces it with a Mac one.
4. Prefer moving the folder out of OneDrive (e.g. to `~/Projects`). Syncing a git folder can
   cause conflicts.

---

## 4. Everyday changes

**GitHub Desktop:** make your changes → the changed files appear → write a summary →
**Commit to main** → **Push origin**. Click **Fetch origin** / **Pull** first if someone else
may have changed something.

**Terminal:**

```bash
git pull                      # get changes from GitHub first
# … make your changes …
.venv/bin/python -m pytest    # optional: run the tests (pip install pytest once)
git add .
git commit -m "Short description of the change"
git push
```

Never commit an API key. Keys belong in environment variables (see the README, *Automatic
AI review*).

---

## 5. Making the next release

1. Raise the version number in **two** places. Use `1.0.1` for fixes and `1.1.0` for new features:
   - `pyproject.toml` → `version = "1.1.0"`
   - `src/price_lens/__init__.py` → `__version__ = "1.1.0"`

   *Settings* in the app shows this number, so colleagues can tell which version they have.
2. Add a section at the top of `CHANGELOG.md` describing what changed.
3. Commit and push (see section 4).
4. Publish a release as in section 2, with the tag `v1.1.0`.

Colleagues update by downloading the new zip and copying their `output` folder into it (see
the README, *Updating to a new version*).
