#!/usr/bin/env python
import rospy
from std_msgs.msg import String
from STMprotocol import STMprotocol
from threading import Lock
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
from std_msgs.msg import Int32MultiArray
import tf
import numpy as np

RATE = 20

GET_ODOMETRY_MOVEMENT_STATUS = 0xa0
GET_MANIPULATOR_STATUS = 0xa1
GET_STARTUP_STATUS = 0xa3
GET_SEC_ROBOT_MANIPULATOR_STATUS = 0xc0
# TAKE_CUBE = 0xb0
MANIPULATOR_JOBS = [0xb0, 0xb1, 0xb2, 0xb3, 0xb4, 0xb5, 0xc1, 0xc2, 0xc3]
IMMEDIATE_FINISHED = [0xc4]
UNLOAD_TOWER = 0xb1
ODOMETRY_MOVEMENT = 0xa2
REQUEST_RF_DATA   = 0xd0
BAUD_RATE = {"main_robot": 250000,
             "secondary_robot": 250000}

class stm_node(STMprotocol):
    def __init__(self, serial_port):
        # ROS
        rospy.init_node('stm_node', anonymous=True)
        rospy.Subscriber("stm_command", String, self.stm_command_callback)
        rospy.Subscriber("cmd_vel", Twist, self.set_twist)
        self.pub_response = rospy.Publisher("response", String, queue_size=10)
        self.pub_odom = rospy.Publisher("odom", Odometry, queue_size=1)
        self.robot_name = rospy.get_param("robot_name")
        
        super(stm_node, self).__init__(serial_port, BAUD_RATE[self.robot_name])
        self.mutex = Lock()


        
        if self.robot_name == "main_robot":
            self.pub_rf = rospy.Publisher("barrier_rangefinders_data", Int32MultiArray, queue_size=10 )
        else:
            self.pub_rf = None
        self.ask_rf_every = 2
        self.rf_it = 0
        self.br = tf.TransformBroadcaster()

        # high-level command IDs
        self.odometry_movement_id = ''

        # storage for timer objects and cmd_names (for 3 manipulators)
        self.timer_m = [None] * 3
        self.take_cube = [''] * 3

        # turn stm inverse kinematics handler ON
        self.send("set_inverse_kinematics_ON", 13, [1])

        # set initial coords in STM
        self.initial_coords = [rospy.get_param('start_x') / 1000.0, rospy.get_param('start_y') / 1000.0,
                               rospy.get_param('start_a')];
        self.send("set_initial_coords", 14, self.initial_coords)

        # get LIDAR coords
        self.laser_coords = (rospy.get_param('lidar_x') / 1000.0, rospy.get_param('lidar_y') / 1000.0, 0.41)
        self.laser_angle = rospy.get_param('lidar_a')

        rospy.Timer(rospy.Duration(1. / 40), self.pub_timer_callback)

    def set_twist(self, twist):
        self.send("set_speed", 8, [twist.linear.x, twist.linear.y, twist.angular.z])

    def parse_data(self, data):
        data_splitted = data.data.split()
        action_name = data_splitted[0]
        action_type = int(data_splitted[1])
        args_str = data_splitted[2:]
        # TODO: split any chars in Strings like 'ECHO'->['E','C','H','O']
        action_args_dict = {'B': int, 'H': int, 'f': float}
        args = [action_args_dict[t](s) for t, s in zip(self.pack_format[action_type][1:], args_str)]
        return action_name, action_type, args

    def stm_command_callback(self, data):
        action_name, action_type, args = self.parse_data(data)
        self.send(action_name, action_type, args)
        if action_type in IMMEDIATE_FINISHED:
            rospy.Timer(rospy.Duration(0.3), lambda e: self.pub_response.publish(action_name + " finished"), oneshot=True)

    def send(self, action_name, action_type, args):

        # Lock() is used to prevent mixing bytes of diff commands to STM
        self.mutex.acquire()
        # send command to STM32
        # rospy.loginfo('Sendid to STM: ' + str(action_type) + '|with args: ' + str(args))
        successfully, args_response = self.send_command(action_type, args)
        self.mutex.release()

        # high-level commands handling
        if action_type == ODOMETRY_MOVEMENT:
            self.odometry_movement_id = action_name
            self.timer_odom_move = rospy.Timer(rospy.Duration(1.0 / RATE), self.odometry_movement_timer)

        if action_type in MANIPULATOR_JOBS:
            n = action_type - 0xc0 # first dynamixel 
            self.take_cube[n] = action_name
            self.timer_m[n] = rospy.Timer(rospy.Duration(1.0 / RATE), self.manipulator_timer(n,
                                                                                             GET_SEC_ROBOT_MANIPULATOR_STATUS if action_type in range(
                                                                                                 0xc1,
                                                                                                 0xc4) else GET_MANIPULATOR_STATUS))

        if action_type == GET_STARTUP_STATUS:
            self.startup_id = action_name
            self.timer_startup = rospy.Timer(rospy.Duration(1. / RATE), self.startup_wire_timer)

        return successfully, args_response

    def publish_odom(self, coords, vel):
        odom = Odometry()
        odom.header.frame_id = '%s_odom' % self.robot_name
        odom.child_frame_id = self.robot_name
        odom.pose.pose.position.x = coords[0]
        odom.pose.pose.position.y = coords[1]
        quat = tf.transformations.quaternion_from_euler(0, 0, coords[2])
        odom.pose.pose.orientation.z = quat[2]
        odom.pose.pose.orientation.w = quat[3]
        odom.twist.twist.linear.x = vel[0]
        odom.twist.twist.linear.x = vel[1]
        odom.twist.twist.angular.z = vel[2]
        self.pub_odom.publish(odom)

        self.br.sendTransform((coords[0], coords[1], 0),
                              tf.transformations.quaternion_from_euler(0, 0, coords[2]),
                              rospy.Time.now(),
                              self.robot_name,
                              "%s_odom" % self.robot_name)

        self.br.sendTransform(self.laser_coords,
                              tf.transformations.quaternion_from_euler(0, 0, self.laser_angle),
                              rospy.Time.now(),
                              '%s_laser' % self.robot_name,
                              self.robot_name)

    def pub_timer_callback(self, event):
        successfully1, coords = self.send('request_stm_coords', 15, [])
        successfully2, vel = self.send('request_stm_vel', 9, [])
        if successfully1 and successfully2:
            self.publish_odom(coords, vel)


        if self.robot_name == "main_robot" and self.rf_it % self.ask_rf_every == 0:
            successfully3, rf_data  = self.send('request_rf_data', REQUEST_RF_DATA, [])
            if successfully3:
                # rospy.loginfo(rf_data)
                self.pub_rf.publish(Int32MultiArray(data=rf_data))
            else:
                rospy.loginfo(successfully3)

        #rospy.loginfo(self.rf_it) 
        #rospy.loginfo(self.ask_rf_every)
        self.rf_it += 1

    def odometry_movement_timer(self, event):
        successfully, args_response = self.send('GET_ODOMETRY_MOVEMENT_STATUS', GET_ODOMETRY_MOVEMENT_STATUS, [])
        if successfully:
            # finished
            if args_response[0] == 0:
                self.pub_response.publish(self.odometry_movement_id + ' finished')
                self.timer_odom_move.shutdown()

    def manipulator_timer(self, n, GET_COMMAND_NAME=GET_MANIPULATOR_STATUS):
        def m_timer(event):
            successfully, args_response = self.send('GET_MANIPULATOR_' + str(n) + '_STATUS', GET_COMMAND_NAME,
                                                    [n] if GET_COMMAND_NAME == GET_MANIPULATOR_STATUS else [])
            if successfully:
                # status code: 0 - done; 1 - in progress; >1 - error
                status = args_response[0]
                # if error 
                if status > 1:
                    rospy.logerr("Manipulator " + str(n) + " error. Code: " + str(status))
                    self.pub_response.publish(self.take_cube[n] + ' error ' + str(status))
                    self.timer_m[n].shutdown()
                # if action is finished
                elif status == 0:
                    self.pub_response.publish(self.take_cube[n] + ' finished')
                    self.timer_m[n].shutdown()

        return m_timer

    def startup_wire_timer(self, event):
        successfully, args_response = self.send('GET_STARTUP_STATUS', GET_ODOMETRY_MOVEMENT_STATUS, [])
        if successfully:
            # finished
            if args_response[0] == 0:
                self.pub_response.publish(self.startup_id + ' finished')
                self.timer_startup.shutdown()


if __name__ == '__main__':
    serial_port = "/dev/ttyUSB0"
    stm = stm_node(serial_port)

    rospy.spin()
