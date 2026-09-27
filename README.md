# KiwiKare

KiwiKare is a clinician portal demo for creating post-procedure care instructions and sharing them with patients through expiring, PIN-protected links.

## Features

- Create care plans with procedure summaries, diet, wound care, medication, activity, warning signs, and follow-up instructions.
- Use quick-fill instruction templates for common care guidance.
- Preview patient details and instructions before sharing.
- Save care plans as JSON manuals in `static/manuals/`.
- Generate patient links that expire after 14 days and require a six-digit PIN.
- Generate patient links and PINs; the demo prints the simulated SMS message in the server terminal. Twilio was not used.
- Optionally generate audio summaries with ElevenLabs text-to-speech.

## Run the project on macOS

Follow these steps the first time you set up the project. Run the commands in the macOS Terminal app, one step at a time.

### Before you start

Install Git and either Miniconda or Anaconda. Open a new Terminal window after installation and check that both commands are available:

```bash
git --version
conda --version
```

### First-time setup

1. Go to the folder where you want to keep the project. This example uses Downloads:

   ```bash
   cd ~/Downloads
   ```

2. Clone the repository. This downloads the project into a new `kiwikare` folder:

   ```bash
   git clone https://github.com/rosytiger/kiwikare.git
   ```

3. Move into the project folder. This folder contains `server.py` and `requirements.txt`:

   ```bash
   cd ~/Downloads/kiwikare
   ```

4. Create a Conda environment with Python 3.10, then activate it. You only need to create this environment once:

   ```bash
   conda create -n kiwikare python=3.10 -y
   conda activate kiwikare
   ```

5. Upgrade pip and install the packages listed in the existing `requirements.txt` file:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

6. Start the web server:

   ```bash
   python -m uvicorn server:app --host 127.0.0.1 --port 8000
   ```

   Leave this Terminal window open while you use the app. The server stays active in this window.

7. Open the clinician portal in your browser: <http://127.0.0.1:8000/clinician>. The interactive API documentation is at <http://127.0.0.1:8000/docs>.

### Use the demo

Enter fictional patient and care-plan details in the clinician portal, then choose **Generate Visual Care Card**. The page displays a patient link and PIN. SMS is not sent in this demo; the simulated message is printed in the Terminal window running the server. Open the link and enter the PIN to view the patient instructions.

### Start the project later

After the first-time setup, you do not need to clone the project, recreate the Conda environment, or reinstall packages each time. Open Terminal and run:

```bash
cd ~/Downloads/kiwikare
conda activate kiwikare
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Then revisit <http://127.0.0.1:8000/clinician>. To stop the server, click the Terminal window and press `Control+C`.

### Troubleshooting

- **`conda: command not found`:** Conda may not be installed or initialized in your shell. Finish the Conda installation, open a new Terminal window, and try `conda --version` again.
- **`git: command not found`:** Install Git, open a new Terminal window, and try `git --version` again.
- **`No such file or directory`:** Check that you used the same folder location as the `git clone` command. If you cloned somewhere other than Downloads, update the `cd` path to match that location.
- **`Address already in use`:** Another process is using port 8000. Start the app on another port with `python -m uvicorn server:app --host 127.0.0.1 --port 8001`, then open <http://127.0.0.1:8001/clinician>.
- **Uvicorn does not start:** Activate the `kiwikare` Conda environment and install the requirements with `python -m pip install -r requirements.txt`.

## Configuration and optional services

Set `BASE_URL` before starting the server if patient links should use a public endpoint. If unset, links use the host and port receiving the request.

| Variable | Purpose |
| --- | --- |
| `BASE_URL` | Optional public base URL used to create patient links. Defaults to the host and port receiving the request. |
| `ELEVENLABS_API_KEY` | Enables optional text-to-speech summaries. |
| `ELEVENLABS_VOICE` | ElevenLabs voice ID for text-to-speech. |

SMS is simulated in this demo: the message and PIN are printed in the server terminal, not sent to a phone. For PIN hashing, install `bcrypt` with `python -m pip install bcrypt`; without it, this demo falls back to storing PINs without secure hashing. ElevenLabs support uses `requests`, which is included in `requirements.txt`.

## Project structure

```text
.
├── server.py                 # FastAPI application and API routes
├── requirements.txt          # Python dependencies
└── static/
    ├── clinician_portal.html # Clinician interface
    ├── manuals/               # Saved care-plan JSON files
    └── uploads/tts/            # Generated audio files
```

The SQLite database (`kiwikare_demo.db`) is created in the project folder when the server starts.

## Demo safety

This project is a demonstration, not a production clinical system. Do not enter real patient information. The demo has no clinician authentication, stores patient details in a local SQLite database, and does not implement production-grade security, privacy, or compliance controls. Review and clinically validate all instructions before use. Configure secure PIN hashing and delivery before testing with anything beyond fictional data.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
