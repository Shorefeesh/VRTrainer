# VRTrainer Client
This is a Python project is a bridge between a PiShock Hub and the game VRChat that enables various trainer-pet interactions.


## Functionality
Run a Whisper model locally to transcribe Trainer/Pet speech.

Read state of contact senders/recievers on the Trainer/Pet VRChat avatars over OSC.

Connect to Pet's PiShock in Web or Serial mode for Pet.

Connect to vrtrainer.online, start/join session.

Trainer-side:
- Control which features are enabled
- Control the delay, cooldown, duration, strength settings
- Run features with access to the following.
  - Trainer speech
  - VRC contacts
  - Server communications

Pet-side:
- Run features with access to the following.
  - Pet speech
  - VRC contacts
  - Server communications
  - PiShock


## Usage
Trainer:
- Navigate to `Trainer` tab
- Set correct `Input Device`
- Select already existing, or create new `Pet Profile`
- Toggle individual features
- Set difficulty sliders
- Set word lists
- Navigate to `Server` tab
- Select `Trainer` role
- Press `Start` or `Join`
- Assign a profile to a joined pet

Pet:
- Navigate to `Pet` tab
- Set correct `Input Device`
- Set correct `PiShock Credentials`
- Navigate to `Server` tab
- Select `Pet` role
- Press `Start` or `Join`


## Workflow
`source venv/bin/activate` Activate venv


## Index
`avatar/` Parameter descriptions
`interfaces/` Interface handlers
`logic/` Feature implementations
`ui/` UI code


## Server
Domain name: vrtrainer.online


## cuBLAS/cuDNN
Download to run Whisper on GPU

https://github.com/Purfview/whisper-standalone-win/releases
