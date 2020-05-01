# wacom follow focus
A service to make a wacom tablet's draw area follow the mouse.

# Installation (Linux)
+ Clone this repository: `git clone https://www.github.com/ep12/wacom_follow_focus`
+ Link the service script and make it executable:
```bash
ln -s wacom_follow_focus/service.py "~/.local/bin/wacom_ff"
chmod a+x wacom_follow_focus/service.py
```
+ start the service: e. g. `wacom_ff --device 'Wacom Intuos BT S Pen stylus' &`
+ Configure your window manager to send `SIGALRM` if your mouse moves to another screen
and `SIGPOLL` if a new monitor was configured.
+ Have fun
