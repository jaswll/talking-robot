from tkinter import Tk, Canvas, Button, Label, PhotoImage, mainloop
import os
from PIL import ImageTk, Image  

WIDTH, HEIGHT = 800, 600
def update():
    try:
        image = ImageTk.PhotoImage(Image.open("./generated/tmp/"+os.listdir("./generated/tmp/")[0]))
        label = Label(image=image)
        label.image = image
        # Position image
        label.place(x=0, y=0)
        if os.listdir("./generated/tmp/")[0] != "zzz.png":
            os.remove("./generated/tmp/"+os.listdir("./generated/tmp/")[0])
    except:
        pass
    master.after(50, update)

master = Tk()

master.after(0, update)  # begin updates
master.mainloop()

