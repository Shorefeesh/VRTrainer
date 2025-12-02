# VRTrainer
This is a Python project is a bridge between a PiSock Hub and the game VRChat that enables various trainer-pet interactions.


## Functionality
Run a Whisper model locally to transcribe Trainer/Pet speech.

Read state of contact senders/recievers on the Trainer/Pet VRChat avatars over OSC.

Connect to Pet's PiShock in UserID + API Key mode for both Pet and Trainer.

Trainer-side:
- Using contact senders/recievers, detect if Pet is looking at Trainer. Fill up focus meter when looking, depelete when not. Deliver a shock if meter gets too low.
- Using contact senders/recievers, detect if Pet is following Trainer closely enough. Deliver a shock if too far away.
- Detect voice commands from Trainer. Use contact senders/recievers to determine completion of command. Deliver a shock if not completed in time.
- Detect scolding words from Trainer. Deliver a shock if detected.

Pet-side:
- Read ear/tail stretch value over OSC, deliver shock if stretched too far.
- Detect first-person speech from Pet, deliver shock if referring to self as 'I', 'me', etc.


## Usage
Trainer:
- Launch the application
- Navigate to `Settings` tab
- Set correct `Input Device`
- Navigate to `Trainer` tab
- Select already existing, or create new `Profile`
- Set PiShock `Username` and `API key`
- Set `Names`, `Command Words`, `Scolding Words`
- Set `Difficulty`
- Toggle individual `Focus`, `Proximity`, `Tricks`, `Scolding` modes
- Press `Start`

Pet:
- Launch the application
- Navigate to `Settings` tab
- Set correct `Input Device`
- Navigate to `Pet` tab
- Set PiShock `Username` and `API key`
- Toggle individual `Ear/Tail Pull`, `Speech` modes
- Press `Start`
