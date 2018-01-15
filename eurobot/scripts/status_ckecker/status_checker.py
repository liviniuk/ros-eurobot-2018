#!/usr/bin/env python
import rospy
from std_msgs.msg import String

def checker():
    pub = rospy.Publisher('/main_robot/stm_command', String, queue_size=10)
    rospy.init_node('status_checker', anonymous=True)

    # set initial coords in STM
    initial_coords = [rospy.get_param('/main_robot/start_x'), rospy.get_param('/main_robot/start_y'), rospy.get_param('/main_robot/start_a')]
    pub.publish("set_initial_coords 14 " + ' '.join(map(str, initial_coords)))
    # TBD: make sure STM recieves this command, it may miss it if

    rate = rospy.Rate(1) # 1hz
    while not rospy.is_shutdown():
        pub.publish("request_stm_status 15")
        rate.sleep()

if __name__ == '__main__':
    try:
        checker()
    except rospy.ROSInterruptException:
        pass
