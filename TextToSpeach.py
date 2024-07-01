from gtts import gTTS
import random
import os
from mutagen.mp3 import MP3

class TextToVoice:
    def __init__(self, language="en", speed="fast"):
        self.lang = language
        self.speed = True if speed == "slow" else False
    
    def get_id(self):
        id = random.randint(0,1000000)
        if str(id)+".mp3" in os.listdir("./generated/voices"):
            return self.get_id()
        return id

    def generate(self, text,id=None):
        gtts = gTTS(text=text, lang=self.lang, slow=self.speed)
        if not id:
            id = self.get_id()
        gtts.save(f"./generated/voices/{id}.mp3")
        audio = MP3(f"./generated/voices/{id}.mp3")
        return({"id":id, "duration":audio.info.length, "path":f"./generated/voices/{id}.mp3", "text":text})

    def delete(self, id):
        os.remove(f"./generated/voices/{id}.mp3")
        return True