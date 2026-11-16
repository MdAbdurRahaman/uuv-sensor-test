# Bottom-track velocity report from a Doppler Velocity Log.
std_msgs/Header header

float64 vx                   # m/s, DVL frame (x forward)
float64 vy                   # m/s (y right)
float64 vz                   # m/s (z down)
float64 fom                  # figure of merit, m/s (lower is better)
float64[9] covariance        # 3x3 velocity covariance, row major
float64 altitude             # m above bottom (-1 if unknown)
string altitude_source       # 'altimeter' (Nucleus vertical beam), 'bottom_track' or ''
bool velocity_valid
uint32 status                # device status word (Nucleus: bottom-track status bit mask)
float64 time_of_validity     # device timestamp, s (0 if unknown)

float32 sound_velocity       # m/s   (NaN if the DVL does not report it)
float32 temperature          # deg C (NaN if not reported)
float32 pressure             # bar   (NaN if not reported)

marine_sensor_msgs/DvlBeam[] beams
