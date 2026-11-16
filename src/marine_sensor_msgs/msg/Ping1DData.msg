# Distance + optional echo profile from a Blue Robotics Ping / Ping2 echosounder
# (both speak the Ping1D protocol).
std_msgs/Header header

float32 distance_m           # distance to target
uint8 confidence             # 0-100 %
uint16 transmit_duration     # microseconds
uint32 ping_number
float32 scan_start_m
float32 scan_length_m
uint32 gain_setting
float32 speed_of_sound       # m/s

uint8[] profile              # echo profile (empty if profile publishing is disabled)
