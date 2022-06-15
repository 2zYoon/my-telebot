# send local files (with compression for directory) via chatbot

import sys, os

import yaml
import shutil
import rpyc

def send_via_chatbot(fname):
    with open(os.path.dirname(os.path.abspath(__file__)) + "/config.yaml") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    
    conn = rpyc.connect("localhost", config['IPC']['PORT'])
    x = conn.root.send_file(fname)

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("[ERROR] This requires exactly one argument")
        quit()

    # relative or absolute? do simple check
    relative = sys.argv[1][0] != "/"
    realpath = (str(os.getcwd()) + "/" + sys.argv[1]) if relative \
                    else sys.argv[1]

    # is directory?
    if os.path.isdir(realpath):
        shutil.make_archive(realpath, 'zip', realpath)
    
        # send file
        send_via_chatbot(realpath + ".zip")

        # cleanup
        os.remove(realpath + ".zip")

    else:
        # send file
        send_via_chatbot(realpath)

    print("Done.")