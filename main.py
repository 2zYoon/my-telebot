import yaml
import telegram
import datetime
import threading 
import os
import sys
import shutil

import MySQLdb as mysql

from telegram.ext import Updater, CommandHandler
from pprint import pprint


###########
# CLASSES #
###########
class Telebot:
    def __init__(self, token, chatid):
        self.core = telegram.Bot(token=token)
        self.updater = Updater(token)
        self.chatid = chatid

        self.updater.stop()

    def add_handler(self, cmd, func):
        self.updater.dispatcher.add_handler(CommandHandler(cmd, func))


#############
# CONSTANTS #
#############
PATH_CONFIG = "config.yaml"
PATH_DATA_DIR = "private/"
PATH_DIARY_DIR = "private/diary/"
PATH_BACKUP = "backup"

PERIOD_POLL_SEC = 5


####################
# GLOBAL VARIABLES #
####################
config = dict()
db = None
cursor = None
bot = None


####################
# COMMON FUNCTIONS #
####################
# checks if the current chat ID is registered
def check_admin(update, context):
    if update.effective_chat.id != bot.chatid:
        context.bot.send_message(chat_id=update.effective_chat.id, 
                                 text="등록되지 않은 사용자입니다.")
        return 1

    return 0

# returns current day in YYMMDD format
def get_now_yymmdd():
    return int(datetime.datetime.now().strftime("%y%m%d"))

def get_now_hhmm():
    return int(datetime.datetime.now().strftime("%H%M"))

###########################
# MULTITHREADED FUNCTIONS #
###########################
# worker for terminating telegram bot
def worker_exit():
    global bot 

    bot.updater.stop()
    bot.updater.is_idle = False

# worker for polling
def worker_poll():
    # alarm
    cursor.execute("select * from alarm where weekday = %d and last != '%s'" % \
        (datetime.datetime.today().weekday(),
         datetime.datetime.now().strftime("%Y-%m-%d"))
    )

    items = cursor.fetchall()

    for i in items:
        if i[1] == get_now_hhmm():
            cursor.execute("update alarm set last = '%s' where name = '%s' and weekday = %d" % \
                (datetime.datetime.now().strftime("%Y-%m-%d"),
                 i[0], 
                 datetime.datetime.today().weekday())
            )

            db.commit()

            msg = "[알람] %s\n%s" % (i[0], i[3])
            bot.core.send_message(chat_id=bot.chatid, text=msg)

    th = threading.Timer(PERIOD_POLL_SEC, worker_poll)
    th.daemon = True
    th.start()


####################
# COMMAND HANDLERS #
####################
def cmd_test(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text="테스트용 명령어입니다.")

def cmd_exit(update, context):
    if check_admin(update, context):
        return

    context.bot.send_message(chat_id=update.effective_chat.id,
                             text="챗봇이 종료됩니다.")

    threading.Thread(target=worker_exit).start()

def cmd_help(update, context):
    if check_admin(update, context):
        return
    
    help_msg = \
'''
/exit
> 텔레그램 챗봇을 종료합니다.
/help
> 사용 도움말을 확인합니다.
/backup
> 챗봇의 데이터를 백업하여 전송합니다. 
/diary <내용>
> 작성한 내용을 다이어리에 저장합니다.
/todo <add|show|remove>
> TODO 리스트를 등록, 확인, 혹은 제거합니다.
/alarm <add|show|remove>
> 알람을 등록, 확인, 혹은 제거합니다.
/eat
> 음식에 대한 리뷰를 기록합니다.
/eatmeta
> 음식 리뷰 관련 정보를 확인합니다.
/eatshow
> 특정 음식 리뷰를 출력합니다.
'''
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text=help_msg)

def cmd_backup(update, context):
    if check_admin(update, context):
        return
    
    shutil.make_archive(PATH_BACKUP, 'zip', PATH_DATA_DIR)
    context.bot.send_message(chat_id=update.effective_chat.id, 
                             text="백업 데이터 파일을 전송합니다.")
    context.bot.send_document(chat_id=update.effective_chat.id, 
                              document=open("%s.zip" % PATH_BACKUP, 'rb'))

def cmd_diary(update, context):
    if check_admin(update, context):
        return
    
    if len(context.args) == 0:
        context.bot.send_message(chat_id=update.effective_chat.id, 
                                 text="/diary [내용]\n> 지정된 내용을 다이어리에 작성합니다.")
        return
    
    content = ' '.join(context.args)
    fname = str(datetime.datetime.now().strftime("%Y_%m.txt"))
    
    # create a new diray if not exist
    if not os.path.isfile(PATH_DIARY_DIR + fname):
        f = open(PATH_DIARY_DIR + fname, 'w')
        f.close()

    # find a header corresponding to current month
    found_header = False
    with open(PATH_DIARY_DIR + fname, "r") as f:
        while 1:
            line = f.readline()
            if not line:
                break
            else:
                tmp = line.split(' ')
                if len(tmp) < 2: # avoid oob indexing
                    continue
                if tmp[0] == "##" and tmp[1].strip() == str(get_now_yymmdd()):
                    found_header = True
                    break
    
    with open(PATH_DIARY_DIR + fname, "a") as f:
        if not found_header:
            f.write("\n## %s" % str(get_now_yymmdd()))

        f.write("\n%s\n" % content)

    context.bot.send_message(chat_id=update.effective_chat.id, 
                             text="다이어리 작성이 완료되었습니다.")


def cmd_eat(update, context):
    if check_admin(update, context):
        return
    
    if len(context.args) < 5:
        context.bot.send_message(chat_id=update.effective_chat.id, 
                                 text="/eat <카테고리> <1차 타입> <2차 타입> <이름> <점수> <코멘트>\n> 먹은 음식을 DB에 기록합니다.\n 타입은 공란일 경우 \".\"으로 표기합니다.")
        return

    if len(context.args) >= 6:
        comment = ' '.join(context.args[5:])
    else:
        comment = ""

    if not context.args[4].isdigit():
        context.bot.send_message(chat_id=update.effective_chat.id, 
                                text='''\
/eat <카테고리> <1차 타입> <2차 타입> <이름> <점수> <코멘트>
> 먹은 음식을 DB에 기록합니다.
- 미리 등록된 카테고리 및 1차 타입만 사용 가능합니다.
- 2차 타입은 공란일 경우 \"X\"로 표기합니다.
- 이름에 띄어쓰기가 필요할 경우 \".\"을 사용합니다.''')
        return


    cursor.execute("SELECT count(*) FROM eat_meta WHERE cat = '{}'".format(context.args[0]))
    if cursor.fetchall()[0][0] == 0:
        context.bot.send_message(chat_id=update.effective_chat.id, 
            text="등록되지 않은 카테고리입니다. /eatmeta에서 카테고리 정보를 확인해주세요.")
        return

    cursor.execute("SELECT count(*) FROM eat_meta WHERE type = '{}'".format(context.args[1]))
    if cursor.fetchall()[0][0] == 0:
        context.bot.send_message(chat_id=update.effective_chat.id, 
            text="등록되지 않은 1차 타입입니다. /eatmeta에서 타입 정보를 확인해주세요.")
        return


    if context.args[2].lower() == "x":
        pass
    else:
        cursor.execute("SELECT count(*) FROM eat_meta WHERE cat = '{}' and type = '{}' and subtype = '{}'".format(context.args[0], context.args[1], context.args[2]))
        if cursor.fetchall()[0][0] == 0:
            cursor.execute("INSERT INTO eat_meta VALUES (NULL, '{}', '{}', '{}', NULL)".format(context.args[0], context.args[1], context.args[2]))
            db.commit()
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                text="새로운 2차 타입의 아이템입니다. 타입 정보를 메타데이터에 기록합니다.")


    query = "insert into eat values ('{}', '{}', {}, '{}', {}, '{}', NULL)".format(
        context.args[0],
        context.args[1],
        "NULL" if context.args[2].lower() == "x" else "'{}'".format(context.args[2]),
        context.args[3].replace(".", " "),
        context.args[4],
        comment)


    try:
        cursor.execute(query)
        db.commit()
    except:
        db.rollback()    
        context.bot.send_message(chat_id=update.effective_chat.id, 
                                text="음식 기록을 실패했습니다. 변경 사항을 롤백합니다.")
        return

    context.bot.send_message(chat_id=update.effective_chat.id, 
                            text="음식 기록이 완료되었습니다.")

def cmd_eatmeta(update, context):
    if check_admin(update, context):
        return

    if len(context.args) < 1:
        context.bot.send_message(chat_id=update.effective_chat.id, 
                                 text="/eatmeta <레벨>\n레벨을 지정하여 카테고리(0), 1차(1), 2차(2)까지 출력합니다.")
        return

    if context.args[0] not in "012":
        context.bot.send_message(chat_id=update.effective_chat.id, 
                                 text="/eatmeta <레벨>\n레벨을 지정하여 카테고리(0), 1차(1), 2차(2)까지 출력합니다.")
        return

    msg = "[리뷰 정보]\n"

    # first level
    cursor.execute("select distinct cat from eat_meta")
    cats = cursor.fetchall()
    cats_dict = dict()
    cnt_sum = 0

    for i in cats:
        cursor.execute("select count(*) from eat where cat = '{}'".format(i[0]))
        cats_dict[i[0]] = cursor.fetchall()[0][0]

    for key, val in cats_dict.items():
        cnt_sum += val
        msg += "[{} 카테고리] ({})\n".format(key, val)

        # second level
        if context.args[0] in "12":
            cursor.execute("select distinct type from eat_meta where cat = '{}'".format(key))
            types = cursor.fetchall()
            types_dict = dict()
            cnt_sum_type = 0

            for j in types:
                cursor.execute("select count(*) from eat where cat = '{}' and type = '{}'".format(key, j[0]))
                types_dict[j[0]] = cursor.fetchall()[0][0]

            for k1, v1 in types_dict.items():
                cnt_sum_type += v1
                msg += "리뷰: {} ({})\n".format(k1, v1)

                # third level
                if context.args[0] in "2":
                    cursor.execute("select distinct subtype from eat_meta where cat = '{}' and type = '{}'".format(key, k1))
                    subtypes = cursor.fetchall()
                    subtypes_dict = dict()
                    cnt_sum_subtype = 0

                    for k in subtypes:
                        cursor.execute("select count(*) from eat where cat = '{}' and type = '{}' and subtype = '{}'".format(key, k1, k[0]))
                        subtypes_dict[k[0]] = cursor.fetchall()[0][0]

                    for k2, v2 in subtypes_dict.items():
                        cnt_sum_subtype += v2
                        if v2 == 0:
                            continue
                        msg += "- {} ({})\n".format(k2, v2)

        msg += "\n" if context.args[0] in "12" else ""

    context.bot.send_message(chat_id=update.effective_chat.id, 
                            text=msg.strip())

def cmd_eatshow(update, context):
    if check_admin(update, context):
        return

    if len(context.args) < 2:
        context.bot.send_message(chat_id=update.effective_chat.id, 
                                 text="/eatshow <카테고리> <1차 타입> [2차 타입]\n> 해당 조건의 리뷰 목록을 출력합니다. ")
        return

    q = "select name from eat where cat = '{}' and type = '{}'".format(context.args[0], context.args[1])
    if len(context.args) == 3:
        q += " and subtype = '{}'".format(context.args[2])

    q += " order by name"

    cursor.execute(q)
    result = cursor.fetchall()

    msg = "[리뷰 목록: {}] (총 {}개)\n".format(
        context.args[1] if len(context.args) == 2 else context.args[2],
        len(result))

    for i in result:
        msg += "- {}\n".format(i[0])


    context.bot.send_message(chat_id=update.effective_chat.id, 
                    text=msg.strip())
  

def cmd_todo(update, context):
    if check_admin(update, context):
        return

    if len(context.args) == 0:
        context.bot.send_message(chat_id=update.effective_chat.id, 
                                 text="/todo <add|show|remove>\n> TODO 리스트를 등록, 확인, 혹은 제거합니다.")
        return
    
    if context.args[0].lower() == "add":
        if len(context.args) < 2:
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                     text="/todo add <내용>")
            return

        content = ' '.join(context.args[1:])
        try:
            cursor.execute("INSERT INTO `todolist` (`id`, `todo`) VALUES (NULL, '{}')".format(content))
            db.commit()
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                    text="TODO 리스트 등록이 완료되었습니다.")  
        except:
            db.rollback()
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                    text="TODO 리스트 등록에 실패했습니다. 변경 사항을 롤백합니다.")  
            return

    elif context.args[0].lower() == "show":
        cursor.execute("select * from todolist")
        items = cursor.fetchall()

        msg = "등록된 TODO 리스트 (총 {} 개)".format(len(items))
        for i in items:
            msg += "\n[{}] {}".format(str(i[0]), i[1])
        
        if len(items) == 0:
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                    text="현재 TODO 리스트에 아이템이 없습니다.")
            return
            

        context.bot.send_message(chat_id=update.effective_chat.id, 
                                text=msg)

    elif context.args[0].lower() == "remove":
        if len(context.args) < 2:
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                     text="/todo remove [id]")
            return
        
        if not context.args[1].isdigit():
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                     text="유효하지 않은 ID입니다.")
            return

        cursor.execute("select count(*) from todolist where id = {}".format(context.args[1]))
        if cursor.fetchall()[0][0] == 0:
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                     text="존재하지 않는 ID입니다.")
            return
        
        try:
            cursor.execute("delete from todolist where id = {}".format(context.args[1]))
            db.commit()
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                     text="TODO 리스트 아이템({})을 삭제했습니다.".format(context.args[1]))
        except:
            db.rollback()
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                     text="TODO 리스트 아이템 삭제에 실패했습니다. 변경 사항을 롤백합니다.")
    else:
        context.bot.send_message(chat_id=update.effective_chat.id, 
                                 text="/todo <add|show|remove>\n> TODO 리스트를 등록, 확인, 혹은 제거합니다.")



def cmd_alarm(update, context):
    if check_admin(update, context):
        return

    if len(context.args) == 0:
        context.bot.send_message(chat_id=update.effective_chat.id, 
                                 text="/alarm <add|show|remove>\n> 알람을 등록, 확인, 혹은 제거합니다.")
        return
    
    if context.args[0].lower() == "add":
        if len(context.args) < 4:
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                     text="/alarm add <이름> <HHMM> <요일|all> [설명]")
            return

        name = context.args[1]
        hhmm = int(context.args[2])
        weekdays = []
        if context.args[3] == "all":
            weekdays = [0, 1, 2, 3, 4, 5, 6]
        else:
            if "월" in context.args[3]:
                weekdays.append(0)
            if "화" in context.args[3]:
                weekdays.append(1)
            if "수" in context.args[3]:
                weekdays.append(2)
            if "목" in context.args[3]:
                weekdays.append(3)
            if "금" in context.args[3]:
                weekdays.append(4)
            if "토" in context.args[3]:
                weekdays.append(5)
            if "일" in context.args[3]:
                weekdays.append(6) 

        if len(context.args) < 5:
            desc = ""
        else:
            desc = ' '.join(context.args[4:])
        
        cursor.execute("select count(*) from alarm where name = '%s'" % name)
        if cursor.fetchall()[0][0] != 0:
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                     text="이미 같은 이름의 알람이 있습니다.")
            return
        
        try:
            for w in weekdays:
                cursor.execute("insert into alarm values ('%s', %d, %d, '%s', '0001-01-01')" % (name, hhmm, w, desc))
            db.commit()
        except:
            db.rollback()
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                    text="알람 등록에 실패했습니다. 변경 사항을 롤백합니다.")  
            return

        context.bot.send_message(chat_id=update.effective_chat.id, 
                                    text="알람 등록이 완료되었습니다.")                            
        
    elif context.args[0].lower() == "show":
        items_map = dict()
        
        cursor.execute("select name, hhmm, weekday from alarm")
        items = cursor.fetchall()
        
        for i in items:
            key = "%s_%d" % (i[0], i[1])
            if items_map.get(key, None) == None:
                items_map[key] = [i[2],]
            else:
                items_map[key].append(i[2])
        
        msg = "등록된 알람 목록 (총 %d 개)\n" % len(items_map)
        for k, v in items_map.items():
            decomp_k = k.split('_')
            msg += "[%s] " % decomp_k[0]

            if len(v) == 7:
                msg += "매일"
            else:
                msg += "매주 "
                tmp_for_weekday = []
                for i in sorted(v):
                    tmp_for_weekday.append(["월", "화", "수", "목", "금", "토", "일"][i])
                msg += ",".join(tmp_for_weekday)
                msg += "요일"

            msg += " %s시 %s분\n" % (decomp_k[1].zfill(4)[0:2], decomp_k[1].zfill(4)[2:])
        
        if len(items) == 0:
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                    text="현재 등록된 알람이 없습니다.")
            return

        context.bot.send_message(chat_id=update.effective_chat.id, 
                                 text=msg)

    elif context.args[0].lower() == "remove":
        if len(context.args) < 2:
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                     text="/alarm remove <이름>")
            return

        name = context.args[1]
        cursor.execute("select count(*) from alarm where name = '%s'" % name)
        if cursor.fetchall()[0][0] == 0:
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                     text="해당 이름을 가진 알람이 없습니다.")
            return
        
        try:
            cursor.execute("delete from alarm where name = '%s'" % name)
            db.commit()
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                     text="알람(%s)을 제거했습니다." % name)
        except:
            db.rollback()
            context.bot.send_message(chat_id=update.effective_chat.id, 
                                     text="알람 제거에 실패했습니다. 변경 사항을 롤백합니다.")
    
    else:
        context.bot.send_message(chat_id=update.effective_chat.id, 
                                 text="/alarm <add|show|remove>\n> 알람을 등록, 확인, 혹은 제거합니다.")


##################
# MAIN FUNCTIONS #
##################

def init():
    global config
    global db
    global cursor
    global bot


    # get configuration from yaml file 
    with open(PATH_CONFIG) as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    
    # connect to DB
    db = mysql.connect(host=config['DB']['HOST'],
                    port=config['DB']['PORT'],
                    user=config['DB']['USER'],
                    passwd=config['DB']['PASSWD'],
                    db=config['DB']['NAME'],
                    charset="utf8")
    cursor = db.cursor()
    

    # set telegram bot
    bot = Telebot(config['TELEBOT']['TOKEN'],
                  config['TELEBOT']['ADMIN_CHATID'])
    
    # commands
    #bot.add_handler('test', cmd_test)  #NOTE: not needed
    bot.add_handler('exit', cmd_exit)
    bot.add_handler('help', cmd_help)
    bot.add_handler('backup', cmd_backup)
    bot.add_handler('diary', cmd_diary)
    bot.add_handler('todo', cmd_todo)
    bot.add_handler('eat', cmd_eat)
    bot.add_handler('eatmeta', cmd_eatmeta)
    bot.add_handler('eatshow', cmd_eatshow)
    bot.add_handler('alarm', cmd_alarm)


def main():
    init()
    threading.Thread(target=worker_poll).start()

    bot.core.send_message(chat_id=bot.chatid, text="챗봇이 준비되었습니다.")
    print("[INFO] 챗봇이 준비되었습니다.")
    bot.updater.start_polling()
    bot.updater.idle()


    print("[INFO] 프로그램이 종료되었습니다.")


main()