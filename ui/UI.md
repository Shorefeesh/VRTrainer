# UI
This document contains the target layout for UI components.


## Main
Main UI container.

### Layout
{tabs:
  Trainer
  Pet
  Session
  Stats
}

`Event Log`
  {text box}

`Whisper Log`
  {text box}

`Connection Status`
  `VRTrainer Server:` {text} | `VRChat OSC:` {text} | `PiShock:` {text} | `Whisper:` {text}


## Trainer
All items relevant to trainer role.

### Layout
`Input device:` {select}

`Profiles`
  {select}
  {button:`New`} {button:`Rename`} {button:`Delete`}

  `Features`
    [] `Focus`
    [] `Proximity`
    [] `Tricks`
    [] `Scolding Words`
    [] `Forbidden Words`
    [] `Word Game` {select}
    [] `Ear/Tail Pull`
    [] `Depth`
    [] `Remote Control`

  `Word Lists`
    `Names (one per line)` | `Scolding (one per line)` | `Forbidden (one per line)`
    {text box} | {text box} | {text box}

  `Difficulty`
    `Delay` {slider} | `Cooldown` {slider}
    `Duration` {slider}  | `Strength` {slider}


## Pet
All items relevant to pet role.

### Layout
`Input device:` {select}

`PiShock Credentials`
  `Web`
    `Username:` {text}
    `API Key:` {text}
    `Sharecode:` {text}
  `Serial`
    `Shocker ID:` {text}


## Session
All items relevant to multiplayer sessions.

### Layout
#### Before join
`Username` {text} | `Role:` {choice:[] `Trainer` [] `Pet`}

{button:`Start Session`} | {button:`Join Session`:action(JoinDialgue)}


#### JoinDialogue
`Enter session ID:`
{text}
{button:`Back`:action(close)} | {button:`Join`:action(validate)}
`Invalid session ID`:on(validateFailInvalid)
`No connection to server`:on(validateFailNoResponse)


#### After join
`Username` {text:locked} | `Role:` {choice:[] `Trainer` [] `Pet`:locked}

`Session`
  `Session ID:` {text:locked}

  {table:
    `User` | `Role` | `VRChat OSC` | `PiShock` | `Whisper` | `Profile`
    User:str
    Role:enum("Trainer", "Pet")
    VRChat OSC:if(role==trainer) str("Message count {int}. Trainer parameters seen {int}/{int}) else str("Message count {int}. Pet parameters seen {int}/{int})
    PiShock: if(role==trainer) str("Not used") else enum("Not configured", "Not connected", "Connected")
    Whisper: enum("Not connected", "CPU", "GPU")
    Profile: if(role==trainer) str("Not used") else {select}
  }


## Stats
Fun pet performance statistics.

### Layout
`Leaderboard`
  `Most obedient:` {text} | `Least obedient:` {text}
  `Most focused:`  {text} | `Least focused:`  {text}
  `Most clingy:`   {text} | `Least clingy:`   {text}

`Graph`
  `Session:` {select}
  {graph}
