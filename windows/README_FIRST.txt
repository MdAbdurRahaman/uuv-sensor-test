MARINE SENSOR BENCH  (Ping360 + Ping2 + Nortek Nucleus1000)  -  ROS 2 Jazzy in WSL Ubuntu-24.04
=========================================================================================

Double-click these in order:

 1_SETUP.bat              One time (and again after updates). Installs the dependencies and builds
                          ~/ros2_ws inside WSL. It asks for your WSL (Linux) password once.

 2_RUN_SIMULATION.bat     Runs everything with simulated sensors and opens http://localhost:8765.
                          Use this to check the dashboard and logging. Close the window to stop.

 4_ATTACH_USB_SENSORS.bat Before using real USB sensors: shares Ping360 / Ping2 (USB) with WSL.
                          Installs usbipd the first time and asks for admin rights.

 3_RUN_REAL_SENSORS.bat   Runs with the real sensors and opens the dashboard.

test_bench.yaml  <- EDIT THIS (Notepad is fine) before running real sensors:
   /ping360:  port:  /dev/serial/by-id/...   (shown by 4_ATTACH_USB_SENSORS.bat)
   /ping1d:   port:  /dev/serial/by-id/...   (this is the Ping2)
   /dvl:      host:  <your Nucleus IP>       (or NORTEK-<serial>.local)
              send_start: true               if the Nucleus is not already measuring
   No rebuild is needed after editing; just run 3_RUN_REAL_SENSORS.bat again.

Logs are saved inside WSL at ~/sensor_logs. From Windows, open:  \\wsl$\Ubuntu-24.04\home\<user>\sensor_logs
You can also download them from the "Log sessions" table on the dashboard.

If the Nucleus can't be reached from WSL, add this to C:\Users\AR\.wslconfig and run "wsl --shutdown":
   [wsl2]
   networkingMode=mirrored
