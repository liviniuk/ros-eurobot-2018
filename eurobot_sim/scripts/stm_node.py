#!/usr/bin/env python
import rospy
from std_msgs.msg import String
import datetime
import numpy as np

class stm_node():
    def __init__(self):
        # ROS
        rospy.init_node('stm_node', anonymous=True)
        rospy.Subscriber("stm_command", String, self.stm_command_callback)
        self.pub_stm_coords = rospy.Publisher('stm/coordinates', String, queue_size=10)
        self.pub_response = rospy.Publisher("response", String, queue_size=10)

        # high-level commands info (for handling response)
        self.actions_in_progress = [''] # action_names, indexing corresponds to types indexing
        self.action_types = [] # list of high-level action types only

        self.pack_format = {
            0x01: "=BBBB",
            0x03: "=Bf",
            0x04: "=B",
            0x05: "=B",
            0x08: "=fff",
            0x09: "=",
            0x0a: "=",
            0x0b: "=BH",
            0x0c: "=B",
            0x0d: "=B",
            0xa0: "=fff",
            0xa1: "=fff",
            0xb0: "=B",
            0xc0: "=BB",
            0xb1: "=B",
            0x0e: "=fff",
            0x0f: "=",
        }

        self.unpack_format = {
            0x01: "=BBBB",
            0x03: "=BB",
            0x04: "=BB",
            0x05: "=BB",
            0x08: "=BB",
            0x09: "=fff",
            0x0a: "=fff",
            0x0b: "=BB",
            0x0c: "=f",
            0x0d: "=BB",
            0xa0: "=Bfff",
            0xa1: "=BB",
            0xb0: "=BB",
            0xc0: "=BB",
            0xb1: "=BB",
            0x0e: "=BB",
            0x0f: "=fff",
        }

        self.freq = 100
        self.rate = rospy.Rate(self.freq) # 100Hz

        self.coords = np.array([0.0, 0.0, 0.0])
        self.vel = np.array([0.0, 0.0, 0.0])


    def parse_data(self, data):
        data_splitted = data.data.split()
        action_name = data_splitted[0]
        action_type = int(data_splitted[1])
        args_str = data_splitted[2:]
        # TBD: split any chars in Strings like 'ECHO'->['E','C','H','O']
        action_args_dict = {'B':ord, 'H':int, 'f':float}
        args = [action_args_dict[t](s) for t,s in zip(self.pack_format[action_type][1:], args_str)]
        return action_name,action_type,args

    def stm_command_callback(self, data):
        # parse data
        action_name,action_type,args = self.parse_data(data)

        ## Command handling
        # simulate STM32 response
        successfuly = True
        args_response = "Ok"
        if action_type == 0x08:
            self.vel = np.array(args)
        elif action_type == 0x09:
            args_response = self.vel
        elif action_type == 0x0E:
            self.coords = np.array(args)
        elif action_type == 0x0F:
            args_response = self.coords
        #elif action_type == 0x0:
            

        if successfuly:
            print 'STM responded to cmd', action_name, '\twith args:', args_response

        # high-level commands handling
        if action_type in self.action_types:
            # store action_name
            self.actions_in_progress[self.action_types[action_type]] = action_name

        # low-level commands handling - not required
        #else:
        #    self.pub_response.publish(action_name + " ok")

        # pub stm/coordinates whenever stm status is requested
        if action_type == 0x0f:
            if successfuly:
                 self.pub_stm_coords.publish(' '.join(map(str, [args_response[0]*1000, args_response[1]*1000, args_response[2]])))
            #self.handle_response()

    def handle_response(self, status):
        """Handles response for high-lvl commands (only)."""
        l = len(status)
        for i in range(l):
            # mind that indeces in status[] correspond to indeces in actions_in_progress[]
            if status[i] == '0' and len(self.actions_in_progress[i]) > 0:
                self.actions_in_progress[i] = ''                                    # stop storing this action_name
                self.pub_response.publish(self.actions_in_progress[i] + " done")    # publish responce

            self.rate.sleep()

    def integrate(self):
        while not rospy.is_shutdown():
            noise = np.random.normal(size=3)
            noise *= 0.1 * self.vel / self.freq
            noise *= 0.94
            self.coords = self.coords + self.vel / self.freq + noise
            self.rate.sleep()

if __name__ == '__main__':
    try:
        stm = stm_node()

        stm.integrate()
    except rospy.ROSInterruptException:
        pass
