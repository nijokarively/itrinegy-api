import socket
import sys
import time
import shlex
import getopt
from collections import defaultdict, ChainMap
import re
import ipaddress

from credentials import itrinegyCredentials


class IT:
    def __init__(self, ipstr, port, username, password):
        self.ipstr = ipstr
        self.port = port
        self.username = username
        self.password = password
        self.session = socket.socket()
        self.session_id = ""
        self.emulation_settings = {
            "object_wh": 80,
            "width": 1900,
            "height": 1200,
            "gw_distance": 300
        }

    def connect(self):

        try:
            # Create a TCP/IP socket
            self.session = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Connect the socket to the port where the server is listening
            server_address = (self.ipstr, self.port)
            self.session.connect(server_address)

        except:
            # TODO: Throw Exception
            print("Socket or connection error while initiating contact with INE")
            self.disconnect()

    def disconnect(self):
        try:
            self.session.close()
        except Exception as ex:
            print(ex)

    def sendCommand(self, command, noSession=False, waitForClose=False):
        self.connect()
        while True:
            # INE expects a new line to end the instruction and you must encode in 'utf-8' otherwise it won't work
            try:
                if not noSession:
                    # Append the session ID to the command
                    self.session.sendall(
                        (self.session_id + ' ' + command + '\n').encode('utf-8'))
                else:
                    # Leave the session ID off
                    self.session.sendall((command + '\n').encode('utf-8'))
                # If function has requested waitForClose
                if waitForClose:
                    # Start with an empty data buffer
                    data = b''
                    while True:
                        try:
                            # Fill the chunk buffer with data received from the iTrinegy socket
                            chunk = self.session.recv(200000)
                            if not chunk:
                                # If we stop receiving data, get out of the loop
                                break
                            # Otherwise add the chunk to the data buffer and go round again
                            data += chunk
                            # TODO: Fix this hideous check to ensure we've received all the data
                            if str(chunk)[-3:] == '\\n\'':
                                break
                        except socket.error as ex:
                            print(ex)
                else:
                    data = self.session.recv(1024)
                # Tidy up the returned string into a readable format
                result = str(data.decode('ascii').rstrip())
                if "Unable to find user session" not in result:
                    return result
                    # Disconnect as per socket good practice
                    self.disconnect()
                    break
                else:
                    # Login and try again
                    print("User session expired, fetching another one...")
                    self.login()
            except BrokenPipeError:
                # Reconnect and try again
                self.connect()

    def login(self):
        # Build login command
        command = '--login "' + self.username + ';' + self.password + '"'
        # Send command with noSession as True as we do not yet have a user session
        result = self.sendCommand(command, True)

        # Fix up the session_id by pulling off trailing LF and spaces, then convert to string
        self.session_id = result
        print("Login successful. SessionID is " +
              self.session_id.replace("--sessionId ", "").replace('"', ""))

    def getRunningEmulations(self):
        # example command - get a list of running emulations
        command = '--getemulations'
        # Send command
        result = self.sendCommand(command)
        # now process the results
        # result will be --emulations "num emulations;emul name;emulation running;emulation notes;default emulation;username;start time;update time..."
        # separate --emulations from the result data
        header, data = result.split(' ', 1)
        # kill off double and single quote chars from front and back
        data = data.strip('"\'')
        parts = data.split(';')  # create an array of the ; separated items
        running_emulation_count = int(parts[0])
        emulations = []
        for emulationNum in range(running_emulation_count):
            emulations.append(
                {"id": int(parts[(emulationNum*8+1)]), "name": parts[(emulationNum*8+2)]})
        return emulations

    def getRunningEmulationbyEmulationID(self, emulationId):
        runningemulations = self.getRunningEmulations()
        try:
            emulation = [d for d in runningemulations if d['id']
                         == int(emulationId)][0]
        except IndexError:
            # TODO: Throw Exception
            emulation = None
        return emulation

    def getPorts(self):
        command = '--getAllPorts'
        result = self.sendCommand(command, False, True)
        if result is not None:
            header, data = result.split(' ', 1)
            # kill off double and single quote chars from front and back
            data = data.strip('"\'')
            parts = data.split(';')  # create an array of the ; separated items
            portCount = int(parts[0])
            # Drop the first entry as it's just a count
            parts.pop(0)
            ports = []
            for PortNum in range(portCount):
                ports.append(
                    {"id": int(parts[(PortNum*6+0)]),
                     "name": parts[(PortNum*6+1)],
                     "parent": int(parts[(PortNum*6+2)]) if parts[(PortNum*6+2)] != "-1" else None,
                     "type": parts[(PortNum*6+4)],
                     "subtype": parts[(PortNum*6+5)] if parts[(PortNum*6+5)] != "" else None
                     })
            return ports

    def getPort(self, portId, parent=False):
        ports = self.getPorts()
        try:
            port = [d for d in ports if d['id'] == int(portId)][0]
        except IndexError:
            # TODO: Throw Exception
            port = None
        if parent and port is not None:
            try:
                parent = [d for d in ports if d['id']
                          == int(port["parent"])][0]
                port["parent"] = parent
            except IndexError:
                port["parent"] = None
        return port

    def deletePort(self, portId):
        command = '--delPortModule ' + str(portId)
        result = self.sendCommand(command, False, False)
        if result == "--ok":
            return True
        # Delete the below code when iTrinegy patches this issue
        bad_port_result = '--error "Port id [' + str(portId) + '] is in use in an emulation and so cannot be deleted"'
        tries = 0
        while not result != bad_port_result or tries == 3:
            print(
                "I'm told it's in use, backing off for a couple of seconds to make sure")
            time.sleep(2)
            print("Trying again...")
            result = self.sendCommand(command, False, False)
            print(result)
            if result == "--ok":
                return True
            tries += 1
        # End of code deletion block
        if result == '--error "Port id [' + str(portId) + '] has a child port and so cannot be deleted':
            return False
        else:
            print(result)
            return False

    def deletePortByAddress(self, address):
        ports = self.getPorts()
        address = str(ipaddress.ip_address(address)-1)
        try:
            port = [d for d in ports if d['name'] == address][0]
            print("I've found the port")
        except IndexError:
            print("I've not found the port")
            return None
        if port is not None:
            try:
                parent = [d for d in ports if d['id']
                          == int(port["parent"])][0]
                port["parent"] = parent
                print("Deleting port", port["id"])
                stop1 = self.deletePort(port["id"])
                print("and the parent", port["parent"]["id"])
                stop2 = self.deletePort(port["parent"]["id"])
            except IndexError:
                return False
        return True

    def createPort(self, wan_number, vlan, address, mask='255.255.255.252', gateway=None):
        interface = None
        if 1 <= wan_number <= 2:
            if wan_number == 1:
                interface = 0
            elif wan_number == 2:
                interface = 1
        else:
            return False
        ports = self.getPorts()
        # Check if the port exists first
        try:
            port = [d for d in ports if d['name'] == address][0]
            parent = [d for d in ports if d['id'] == int(port["parent"])][0]
            port["parent"] = parent
        except IndexError:
            port = None

        if port:
            print("Port found")
            if port["parent"]["name"] != interface + "." + vlan:
                print("Existing port VLAN is not the same, deleting...")
                self.deletePort(port["id"])
                self.deletePort(port["parent"]["id"])
            else:
                print("Port already appears to be correct")
                return False
        else:
            print("Port does not exist, creating it")

        command = '--portModule "Default:Hardware_VLAN_Routing;' + str(interface) + ';VLAN_Interfaces[0].Interface_Name;' + str(interface) + '.' + str(
            vlan) + ';VLAN_Interfaces[0].Use_As_Default_Interface;False;VLAN_Interfaces[0].VLAN_Id;' + str(vlan) + ';VLAN_Interfaces[0].Detag_Packets_on_Output;False"'
        result = self.sendCommand(command, False, False)
        print(result)
        command = '--portModule "Default:Hardware_IPv4_Routing;' + str(interface) + '.' + str(vlan) + ';IPv4_Interfaces[0].Netmask;' + str(mask) + ';IPv4_Interfaces[0].Interface_Name;' + str(address) + ';IPv4_Interfaces[0].Gateway;' + (
            str(gateway) if gateway is not None else '') + ';IPv4_Interfaces[0].Accept_Multicast_Traffic;No;IPv4_Interfaces[0].Address;' + str(address) + ';IPv4_Interfaces[0].Use_DHCP_Relay;No"'
        result = self.sendCommand(command, False, True)
        print(result)
        return True

    def getAllVis(self):
        emulations = self.getRunningEmulations()
        if emulations is not None:
            viList = []
            for emulation in emulations:
                viList.append(self.getVisByEmulationId(emulation["id"]))
            return viList
        else:
            return None

    def getVisByEmulationId(self, emulationId):
        command = '--emulationId ' + str(emulationId) + ' --getVIsForEmulation'
        result = self.sendCommand(command)
        if result is not None:
            # separate --VIsForEmulation from the result data
            header, data = result.split(' ', 1)
            # kill off double and single quote chars from front and back
            data = data.strip('"\'')
            # create an array of the ; separated items
            vi_Ids = data.split(';')
            # Remove the last one as it's just a blank line
            vi_Ids.pop(len(vi_Ids)-1)
            # Remove the first as that is also just rubbish
            vi_Ids.pop(0)
            # Create a list to fill in the next step
            viList = []
            for vi in vi_Ids:
                viList.append(self.getViByViId(vi))

            return viList
        else:
            return None

    def getViIdsByEmulationIdAndViName(self, emulationId, names=['Internet', 'MPLS'], impairments=False):
        vis = self.getVisByEmulationId(emulationId)
        namedVis = [d for d in vis if d['name'] in names]
        if impairments:
            for i, vi in enumerate(namedVis):
                namedVis[i]["impairments"] = self.getImpairmentsByViId(
                    vi["id"])
        return namedVis

    def getViByViId(self, vi_id):
        command = '--Id ' + str(vi_id) + ' --getVISettings'
        # Send the command
        result = self.sendCommand(command, False, True)
        # Split the results into a list
        result = shlex.split(result)
        # Get all posible arguments in the list and compile it into a dictionary
        try:
            optlist = getopt.getopt(result, '', ['id=', 'name=', 'setUserGivenId=', 'vitype=', 'groupname=', 'xpos=',
                                                 'ypos=', 'width=', 'height=', 'objdir=', 'image=', 'notes=', 'meta=', 'procModule='])[0]
            full_list = defaultdict(list)
            for k, v in optlist:
                if k == "--procModule":
                    full_list[self.removeDashes(str(k))].append(v)
                else:
                    full_list.update({
                        self.removeDashes(str(k)): v
                    })
        except getopt.GetoptError:
            full_list = None
        return full_list

    def getImpairmentsByViId(self, vi_id):
        try:
            latency = self.getLatencyByViId(vi_id)["latency"]
            loss = self.getLossByViId(vi_id)["loss"]
            errors = self.getErrorsByViId(vi_id)["errors"]
            impairments = {
                "latency": latency,
                "loss": loss,
                "errors": errors
            }
        except TypeError:
            return None

        return impairments

    def getLatencyByViId(self, vi_id):
        vi = self.getViByViId(vi_id)
        if vi is not None:
            sub = 'Default:Random_Delay;50;Min_Delay;'
            latency = next((s for s in vi['procModule'] if sub in s), None)
            if not latency:
                return {"latency": 0}
            else:
                return {"latency": int(float(latency.replace(sub, '').replace(';Max_Delay;', ':').split(':')[0]))*2}
        else:
            return None

    def getLossByViId(self, vi_id):
        vi = self.getViByViId(vi_id)
        if vi is not None:
            sub = 'Default:Random_Drop;30;Loss_Percent;'
            loss = next((s for s in vi['procModule'] if sub in s), None)
            if not loss:
                return {"loss": 0}
            else:
                return {"loss": int(float(loss.replace(sub, '').replace(';', '')))*2}
        else:
            return None

    def getErrorsByViId(self, vi_id):
        vi = self.getViByViId(vi_id)
        if vi is not None:
            sub = 'Default:Random_Packet_Corrupt;40;Packet_Corruption_Percent;'
            errors = next((s for s in vi['procModule'] if sub in s), None)
            if not errors:
                return {"errors": 0}
            else:
                return {"errors": int(float(errors.replace(sub, '').replace(';', '')))*2}
        else:
            return None

    def resetAllImpairmentsByViId(self, vi_id):
        impairments = []
        impairments.append(self.applyLatency(vi_id, 0))
        impairments.append(self.applyLoss(vi_id, 0))
        impairments.append(self.applyErrors(vi_id, 0))
        return impairments

    def applyLatency(self, vi_id, latency_value):
        latency_value = latency_value/2
        command = '--Id ' + str(vi_id) + ' --procModule "Default:Random_Delay;50;Min_Delay;' + \
            str(latency_value) + ';Max_Delay;' + \
            str(latency_value+0.1) + ';"'
        print(command)
        result = self.sendCommand(command)
        if result == "--ok":
            return {'latency': latency_value*2}

    def applyLoss(self, vi_id, loss_percent):
        loss_percent = loss_percent/2
        command = '--Id ' + str(vi_id) + ' --procModule "Default:Random_Drop;30;Loss_Percent;' + \
            str(loss_percent) + ';"'
        result = self.sendCommand(command)
        if result == "--ok":
            return {'loss': loss_percent*2}

    def applyErrors(self, vi_id, error_percent):
        error_percent = error_percent/2
        command = '--Id ' + str(vi_id) + ' --procModule "Default:Random_Packet_Corrupt;40;Packet_Corruption_Percent;' + \
            str(error_percent) + ';"'
        result = self.sendCommand(command)
        if result == "--ok":
            return {'errors': error_percent*2}

    def stopRunningEmulation(self, emulationId):
        emulation = self.getRunningEmulationbyEmulationID(emulationId)
        if emulation is not None:
            print("Stopping emulation...")
            command = '--emulationId ' + str(emulationId) + ' --stop'
            result = self.sendCommand(command)
            if result == "--ok":
                return "Emulation stopped"
        else:
            return None

    def createEmulation(self, product, devices, overwrite=None):
        emulations = self.getRunningEmulations()
        for emulation in emulations:
            if emulation["name"] == product.name:
                if overwrite:
                    self.stopRunningEmulation(emulation["id"])
                else:
                    return {"message": "Emulation already running",
                            "emulation": emulation}, 400

        command = '--addEmulation "' + product.name + '"'
        emulationId = self.sendCommand(command)

        # Instantiate the FW
        FW_Vi = {"name": "Firewall",
                 "xpos": ((self.emulation_settings["width"]/2)-self.emulation_settings["object_wh"]/2),
                 "ypos": self.emulation_settings["height"]-280,
                 # Add the product gateway IP
                 "address": ipaddress.ip_address(product.gateway_ip)+1,
                 "mask": "255.255.255.252",
                 "gateway": ipaddress.ip_address(product.gateway_ip),
                 "vlan": product.vlan.vlan,
                 "number": 1}  # Set a FW port to 1

        # Instantiate the Outer VI
        Outer_Vi = {"name": "Outer",
                    "xpos": FW_Vi["xpos"],
                    "ypos": FW_Vi["ypos"]-100,
                    "routes": []}

        # Instantiate the Internet VI
        Internet_Vi = {"name": "Internet",
                       "xpos": Outer_Vi["xpos"]-self.emulation_settings["gw_distance"],
                       "ypos": Outer_Vi["ypos"]-150,
                       "routes": []}

        # Instantiate the MPLS VI
        MPLS_Vi = {"name": "MPLS",
                   "xpos": Outer_Vi["xpos"]+self.emulation_settings["gw_distance"],
                   "ypos": Outer_Vi["ypos"]-150,
                   "routes": []}

        # Define the link to add at the end
        FW_Vi["parent"] = Outer_Vi["name"] + " Link: " + \
            FW_Vi["name"] + " --> " + Outer_Vi["name"]

        # Instantiate the links
        vis = []
        vis.extend(self.createLinkVi(emulationId, MPLS_Vi, Outer_Vi))
        vis.extend(self.createLinkVi(emulationId, Internet_Vi, Outer_Vi))
        vis.extend(self.createLinkVi(emulationId, Outer_Vi, FW_Vi))

        ### Build the devices ###
        wan1_positions = {"xpos": Internet_Vi["xpos"] - 210,
                          "ypos": 220}
        wan2_positions = {"xpos": MPLS_Vi["xpos"] + 210,
                          "ypos": 220}
        device_vis = []
        for device in devices:
            if device.wan1 is not None:
                Device_Vi = {}  # Create the dict before we can use it
                Device_Vi["number"] = 1
                Device_Vi["gateway"] = str(
                    ipaddress.ip_address(device.wan1.address.address))
                Device_Vi["address"] = str(
                    ipaddress.ip_address(device.wan1.address.address)-1)
                Device_Vi["mask"] = str(ipaddress.ip_network(
                    device.wan1.address.address + "/" + str(device.wan1.address.mask), strict=False).netmask)
                Device_Vi["vlan"] = device.wan1.vlan.vlan
                Device_Vi["name"] = device.name + '-GW0'
                Device_Vi["type"] = "device"

                Device_Vi["xpos"] = wan1_positions["xpos"]
                Device_Vi["ypos"] = wan1_positions["ypos"]
                Device_Vi["parent"] = "Internet"
                Internet_Vi["routes"].append(
                    {"ip": Device_Vi["address"], "mask": Device_Vi["mask"], "portOut": Device_Vi["name"]})
                Outer_Vi["routes"].append(
                    {"ip": Device_Vi["address"], "mask": Device_Vi["mask"], "portOut": Internet_Vi["name"] + ' Link: ' + Outer_Vi["name"] + " --> " + Internet_Vi["name"]})
                # Move the next object down
                wan1_positions["ypos"] += self.emulation_settings["object_wh"] + \
                    self.emulation_settings["object_wh"]/4
                device_vis.append(Device_Vi)

            if device.wan2 is not None:
                Device_Vi = {}  # Create the dict before we can use it
                Device_Vi["number"] = 2
                Device_Vi["gateway"] = str(
                    ipaddress.ip_address(device.wan2.address.address))
                Device_Vi["address"] = str(
                    ipaddress.ip_address(device.wan2.address.address)-1)
                Device_Vi["mask"] = str(ipaddress.ip_network(
                    device.wan2.address.address + "/" + str(device.wan2.address.mask), strict=False).netmask)
                Device_Vi["vlan"] = device.wan2.vlan.vlan
                Device_Vi["name"] = device.name + '-GW1'
                Device_Vi["type"] = "device"

                Device_Vi["xpos"] = wan2_positions["xpos"]
                Device_Vi["ypos"] = wan2_positions["ypos"]
                Device_Vi["parent"] = "MPLS"
                MPLS_Vi["routes"].append(
                    {"ip": Device_Vi["address"], "mask": Device_Vi["mask"], "portOut": Device_Vi["name"]})
                Outer_Vi["routes"].append(
                    {"ip": Device_Vi["address"], "mask": Device_Vi["mask"], "portOut": MPLS_Vi["name"] + ' Link: ' + Outer_Vi["name"] + " --> " + MPLS_Vi["name"]})
                # Move the next object down
                wan2_positions["ypos"] += self.emulation_settings["object_wh"] + \
                    self.emulation_settings["object_wh"]/4
                device_vis.append(Device_Vi)

        Internet_Vi["routes"].append({"ip": '0.0.0.0', "mask": '0.0.0.0', "portOut": Internet_Vi["name"] +
                                      ' Link: ' + Internet_Vi["name"] + " --> " + Outer_Vi["name"]})
        MPLS_Vi["routes"].append({"ip": '0.0.0.0', "mask": '0.0.0.0', "portOut": MPLS_Vi["name"] +
                                  ' Link: ' + MPLS_Vi["name"] + " --> " + Outer_Vi["name"]})
        Outer_Vi["routes"].append({"ip": '0.0.0.0', "mask": '0.0.0.0', "portOut": Outer_Vi["name"] +
                                   ' Link: ' + Outer_Vi["name"] + " --> " + FW_Vi["name"]})

        for vi in device_vis:
            vis.append(self.createObjectVi(emulationId, vi))
        vis.append(self.createObjectVi(emulationId, MPLS_Vi))
        vis.append(self.createObjectVi(emulationId, Internet_Vi))
        vis.append(self.createObjectVi(emulationId, Outer_Vi))
        vis.append(self.createObjectVi(emulationId, FW_Vi))

        for vi in vis:
            self.amendVi(emulationId, vi)

        # Finally, start the emulation
        command = emulationId + ' --start'
        result = self.sendCommand(command)
        print("Result:", result)
        return {"id": int(emulationId.replace("--emulationId ", "")),
                "name": product.name}

    def createObjectVi(self, emulationId, vi):
        vi["id"] = self.createVi(emulationId, vi["name"])
        vi["width"] = vi["height"] = self.emulation_settings["object_wh"]
        if not vi.get("objdir"):
            vi["objdir"] = 0
        return vi

    def amendVi(self, emulationId, vi):
        command = '--id ' + vi["id"] + ' '
        groupname = vi["name"]
        vitype = "picture"
        # Mandatory procs need applying
        command += '--procModule "Default:Debug;10;Dump_Packet;0;Bytes_to_Dump;80;" ' + \
                   '--procModule "Default:Generic_Filter;20;" ' + \
                   '--procModule "Default:Random_Drop_with_Burst;30;Loss_Percent;0.0;Minimum_Packets_to_Drop;1;Maximum_Packets_to_Drop;1;" ' + \
                   '--procModule "Default:Random_Packet_Corrupt;40;Packet_Corruption_Percent;0.0;" ' + \
                   '--procModule "Default:Step_Delay_Packet_Nanoseconds;50;Min_Delay;0;Max_Delay;0;Step_Delay;0;" ' + \
                   '--procModule "Default:Fragment_MTU;55;MTU_Limit;0;Dont_Fragment_Flag_Option;Fragment Anyway;" '
        # Apply routing depending on which type of object it is
        if vi.get("address"):
            command += '--procModule "Default:Symmetric_Routing;60;'
            if vi.get("parent"):
                command += 'Routes[0].Port_Out;' + vi["parent"] + \
                    ';Routes[0].Port_In;' + str(vi["address"]) + ';'
            command += 'Port_In;' + \
                str(vi["address"]) + ';Port_Out;' + str(vi["address"]) + ';" '
            image = 'LAN/Port.png'
        else:
            image = 'Standard/Router.png'
        if vi["objdir"] > 0:
            command += '--procModule "Default:Generic_Routing;60;' + \
                       'Port_In;Virtual;' + \
                       'Port_Out;' + vi["parent"] + ';" '
            image = 'Standard/FullDuplex.png'
            groupname = vi["groupname"]
            vitype = "lineobject"
        if vi.get("routes"):
            command += '--procModule "Default:IPv4_Routing;60;'
            for routeNumber, route in enumerate(vi["routes"]):
                net = ipaddress.ip_network(
                    route["ip"] + '/' + route["mask"], strict=False)
                command += 'Routes[' + str(routeNumber) + '].Route_Disabled;0;' + \
                    'Routes[' + str(routeNumber) + '].Port_In;Virtual;' + \
                    'Routes[' + str(routeNumber) + '].Port_Out;' + route["portOut"] + ';' + \
                    'Routes[' + str(routeNumber) + '].Network_Mask;' + str(net.netmask) + ';' + \
                    'Routes[' + str(routeNumber) + '].Network_Address;' + \
                    str(net.network_address) + ';'
            command += 'Port_In;;Port_Out;;" '

        # Now for more mandatory procs
        command += '--procModule "Default:Packet_Move_and_Duplicate;62;Selection_Percent;0.0;Duplicate_Packet;0;Minimum_Move;0;Maximum_Move;0;" ' + \
                   '--procModule "Default:Random_Packet_Move_Offset;65;Move_Percent;0.0;Minimum_Move;1;Maximum_Move;1;" ' + \
                   '--procModule "Default:Linkspeed_and_FIFO_Queue_Bytes;70;Link_Type;Manual;Link_Speed;0;Queue_Length;64000;Overhead;18;Congestion_PCT;0.0;TTL_Cost;0;" '
        if vitype == "lineobject":
            command += '--procModule "Default:;80;" '

        command += '--vitype "' + vitype + '" '
        command += '--groupname "' + groupname + '" '
        command += '--xpos ' + str(vi["xpos"]) + ' --ypos ' + str(vi["ypos"]) + ' --width ' + str(vi["width"]) + ' --height ' + \
            str(vi["height"]) + ' --objdir ' + str(vi["objdir"]) + ' '
        command += '--image "' + image + '" '
        command += '--notes "" '

        result = self.sendCommand(command)
        if vi.get("address"):
            # Delete the below code when iTrinegy patches this issue
            bad_port_result = '--error "[' + vi["name"] + ' - Default:Symmetric_Routing]: Object ' + vi["name"] + \
                ': Cannot Open a connection to Input port (' + str(
                    vi["address"]) + ') - likely it\'s already in use"'
            tries = 0
            while not result != bad_port_result or tries == 3:
                print(
                    "I'm told the port I need is in use, backing off for a couple of seconds")
                time.sleep(1)
                print("Trying again...")
                result = self.sendCommand(command)
                tries += 1
            # End of code deletion block
            if result == '--error "[' + vi["name"] + ' - Default:Symmetric_Routing]: Object ' + vi["name"] + ': No such port (' + str(vi["address"]) + ')"':
                print("Looks like the port doesn't exist...")
                self.createPort(vi["number"], vi["vlan"],
                                vi["address"], vi["mask"], vi["gateway"])
                result = self.sendCommand(command)
            else:
                print(result)
        else:
            print(result)

    def createLinkVi(self, emulationId, from_vi, to_vi):
        link_name = from_vi["name"] + " Link"
        links = [
            {"name": link_name + ': ' +
                from_vi["name"] + ' --> ' + to_vi["name"], "parent": to_vi["name"]},
            {"name": link_name + ': ' +
                to_vi["name"] + ' --> ' + from_vi["name"], "parent": from_vi["name"]}
        ]

        xpos = int(from_vi["xpos"]) + (self.emulation_settings["object_wh"]/2)
        ypos = int(from_vi["ypos"]) + (self.emulation_settings["object_wh"]/2)
        width = int(to_vi["xpos"]) - int(from_vi["xpos"])
        height = int(to_vi["ypos"]) - int(from_vi["ypos"])
        objdir = 1
        if width < 0:
            width = abs(width)
            xpos = int(to_vi["xpos"]) + \
                (self.emulation_settings["object_wh"]/2)
            objdir += 1
        elif width == 0:
            width = 2
            xpos -= 5
            objdir = 2
        if height < 0:
            height = abs(height)
            ypos = int(to_vi["ypos"]) + \
                (self.emulation_settings["object_wh"]/2)
            objdir += 2
        elif height == 0:
            height = 2
            ypos -= 5
        vis = []
        for link in links:
            vis.append({"name": link["name"], "parent": link["parent"], "id": self.createVi(emulationId, link["name"]), "xpos": int(xpos), "ypos": int(
                ypos), "width": int(width), "height": int(height), "objdir": objdir, "groupname": link_name})
        return vis

    def createVi(self, emulationId, name):
        return self.sendCommand(emulationId + ' ' + '--addVi "' + str(name) + '"').replace("--id ", "")

    def removeDashes(self, variable):
        variable = variable.replace("--", "")
        return variable


iTrinegyCredentials = itrinegyCredentials()
it = IT(iTrinegyCredentials["ip"], iTrinegyCredentials["port"],
        iTrinegyCredentials["username"], iTrinegyCredentials["password"])
print("Attempting to login to iTrinegy on IP " +
      iTrinegyCredentials["ip"] + ":" + str(iTrinegyCredentials["port"]))
it.login()
print("We're logged in to iTrinegy INE")


def create_emulation(product, devices, overwrite=None):
    return it.createEmulation(product, devices, overwrite)


def create_port(wan_number, vlan, address, mask, gateway=None):
    return it.createPort(wan_number, vlan, address, mask, gateway)


def delete_port_by_port_id(port_id):
    delete_port = it.deletePort(port_id)
    if delete_port:
        if delete_port is not None:
            return {"message": 'Port was deleted successfully'}, 200
        else:
            return {"message": 'Port not found'}, 404
    else:
        return {"message": 'Port currently in use'}, 403


def delete_port_by_port_address(port_address):
    delete_port = it.deletePortByAddress(port_address)
    if delete_port is not None:
        if delete_port:
            return {"message": 'Port was deleted successfully'}, 200
    else:
        return {"message": 'Port currently in use'}, 403


def get_emulation_by_emulation_id(emulation_id):
    emulation = it.getRunningEmulationbyEmulationID(emulation_id)
    if emulation is not None:
        return emulation
    else:
        return {"message": 'Emulation not found'}, 404


def get_emulations():
    return it.getRunningEmulations()


def get_errors_by_vi_id(vi_id):
    errors = it.getErrorsByViId(vi_id)
    if errors is not None:
        return errors
    else:
        return {"message": 'VI not found'}, 404


def get_impairments_by_vi_id(vi_id):
    impairments = it.getImpairmentsByViId(vi_id)
    if impairments is not None:
        return impairments
    else:
        return {"message": 'VI not found'}, 404


def get_latency_by_vi_id(vi_id):
    latency = it.getLatencyByViId(vi_id)
    if latency is not None:
        return latency
    else:
        return {"message": 'VI not found'}, 404


def get_loss_by_vi_id(vi_id):
    loss = it.getLossByViId(vi_id)
    if loss is not None:
        return loss
    else:
        return {"message": 'VI not found'}, 404


def get_port_by_port_id(port_id, parent=None):
    if parent:
        port = it.getPort(port_id, True)
    else:
        port = it.getPort(port_id)
    if port is not None:
        return port
    else:
        return {"message": 'Port not found'}, 404


def get_ports():
    return it.getPorts()


def get_router_vis_by_emulation_id(emulation_id, reset=None, firewall=None):
    vis = []
    if firewall:
        vis = it.getViIdsByEmulationIdAndViName(
            emulation_id, ['Internet', 'MPLS', 'Firewall'], True)
    else:
        vis = it.getViIdsByEmulationIdAndViName(
            emulation_id, ['Internet', 'MPLS'], True)
    if reset:
        for vi in vis:
            it.resetAllImpairmentsByViId(vi['id'])

    return vis


def get_vi_by_vi_id(vi_id):
    vi = it.getViByViId(vi_id)
    if vi is not None:
        return vi
    else:
        return {"message": 'VI not found'}, 404


def get_vis():
    return it.getAllVis()


def get_vis_by_emulation_id(emulation_id):
    vis = it.getVisByEmulationId(emulation_id)
    if vis is not None:
        return vis
    else:
        return {"message": 'Emulation not found'}, 404


def reset_errors_by_vi_id(vi_id):
    return it.applyErrors(vi_id, 0)


def reset_impairments_by_vi_id(vi_id):
    result = it.resetAllImpairmentsByViId(vi_id)
    return dict(ChainMap(*result))


def reset_latency_by_vi_id(vi_id):
    return it.applyLatency(vi_id, 0)


def reset_loss_by_vi_id(vi_id):
    return it.applyLoss(vi_id, 0)


def set_impairments_by_vi_id(vi_id, latency=None, loss=None, errors=None):
    result = []
    if latency is not None:
        result.append(it.applyLatency(vi_id, latency))
    if loss is not None:
        if 0 <= loss <= 100:
            lossvalue = it.applyLoss(vi_id, loss)
            result.append(lossvalue)
        else:
            return {"message": 'Loss percentage out of range'}, 400
    if errors is not None:
        if 0 <= errors <= 100:
            result.append(it.applyErrors(vi_id, errors))
        else:
            return {"message": 'Error percentage out of range'}, 400
    if result != []:
        return dict(ChainMap(*result))
    else:
        return {"message": 'No impairments provided'}, 400


def stop_emulation_by_emulation_id(emulation_id):
    result = it.stopRunningEmulation(emulation_id)
    if result is not None:
        return result
    else:
        return {"message": 'Emulation not found'}, 404
