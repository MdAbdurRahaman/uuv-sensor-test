# Dead-reckoning estimate reported by the DVL itself.
std_msgs/Header header

float64 x                    # m, relative to last reset
float64 y
float64 z
float64 std                  # position standard deviation, m
float64 roll                 # degrees
float64 pitch
float64 yaw
uint8 status
