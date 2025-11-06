Cadence Joules RTL Power Tool Plugin
====================================

Tool Steps
----------

See ``__init__.py`` for the implementation of these steps.

    init_design
    synthesize_design
    report_power


A variety of different output reports may be generated with this tool.
Within the [Hammer default configs file](https://github.com/ucb-bar/hammer/blob/joules-fixes/hammer/config/defaults.yml),
the `power.inputs.report_configs` struct description
contains a summary of the different reporting options, specified via the `output_formats` struct field.

Power Reporting
---------------

* Make sure you know what sshing is, its basically accessing a remote server that's protected from corruption through your personal username and password.
* Download a VPN (Palo Alto Network), will allow you to remotely access the server via the ssh command (Ex: ssh bwrcr 740-8). The SSH command will not work unless you connect to VPN or are on campus wifi.
* Add the SSHing possibility to your code editor (Ex: VSCode), makes coding much easier than using vim to access file code.
* Start by creating your own repository by cloning the git repository given by your professor/Phd Student into your personal username.
* Download and setup Hammer, which is Berkeley's custom tool for running through ASIC Design.
* In your makefile within Hammer, set tools = cm so you don't have to keep specifying it in your make commands.
* cd into your username, then to hammer
* Run the following commands in order: make build, make sim-rtl, make power-rtl. This simulates the whole ASIC Design process running for you, will take a few minutes to finish. There are more commands you could run, but for the sake of power reporting we only care about these three.
* If you need to rerun the make commands, do 'make -B build'. Add '-B' to the rest of the commands too.
* To access the reports, follow the path - /users/Username/hammer/e2e/build-sky130-cm/pass/power-rtl-rundir/reports/

Known Issues
------------

* Joules supports saving the read stimulus file to the SDB (stimulus database) format via the `write_sdb` command. However, subsequent reads of this SDB file via the `read_sdb` command fail for no apparent reason
  * As a result, `read_stimulus`/`compute_power` cannot be a separate step in the plugin, because there is no way to save the results of these commands before running the various power reporting commands.
    Thus these two commands are run as part of the `report_power` step.
  * NOTE: this might not be a problem anymore with the new Joules version, so we should re-try this!!



