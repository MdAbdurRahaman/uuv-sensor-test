# One transducer ping from a Blue Robotics Ping360 scanning sonar.
std_msgs/Header header

uint16 angle                 # head angle in gradians (0-399, 400 = full circle)
float32 angle_deg            # same angle in degrees (0-360)
float32 range_m              # max range covered by `intensities`
float32 speed_of_sound       # m/s used for range calculation

uint8 mode
uint8 gain_setting           # 0 = low, 1 = normal, 2 = high
uint16 transmit_duration     # microseconds
uint16 sample_period         # ticks of 25 ns
uint16 transmit_frequency    # kHz
uint16 number_of_samples

uint8[] intensities          # echo strength per sample, 0-255, near -> far
