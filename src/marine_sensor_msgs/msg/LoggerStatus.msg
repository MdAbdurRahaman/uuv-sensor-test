std_msgs/Header header

bool active
string session_name
string directory             # absolute path of the current/last session
float64 elapsed_s
bool bag_recording           # true if a rosbag2 recording runs alongside the CSVs

string[] streams             # e.g. ["ping360", "ping1d", "dvl", "dvl_position"]
uint64[] rows                # rows written per stream (same order as `streams`)
