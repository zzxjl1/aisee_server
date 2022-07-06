import json
from database import DBSession
import models

def delete(id):
    db.query(models.Article).filter(models.Article.id == id).delete()
    db.commit()


db = DBSession()
news_list = db.query(models.Article).all()
for news in news_list:
    #print(news.content)
    try:
        content=json.loads(news.content)
        for item in content:
            if item["type"] == "img_with_caption" and len(item["caption"])>50:
                print(news.title)
                delete(news.id)
                break
    except Exception as e:
        print(e)
        delete(news.id)
        continue
        