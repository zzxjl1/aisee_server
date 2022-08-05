from datetime import datetime
from pickle import LIST
import random
import curd
from sqlalchemy.orm import Session
import models

# 消除噪声 eg：用户点开了一篇文章，但是很快关闭了，那么视为噪声
ANTI_NOICE_THRESHOLD_IN_MILLISECONDS = 2 * 1000
FETCH_VIEW_HISTORY_LIMIT = 100  # 每次从数据库查询的历史记录条数（推荐过程中）
FETCH_NEWS_FACTOR = 3  # 每次从数据库查询的新闻放大倍数（推荐过程中）
RECOMMEND_RESULT_LIMIT = 20  # 默认的推荐结果个数


class Cache():
    def __init__(self):
        self.data = {}
        pass

    def init_by_user_id(self, user_id: int) -> None:
        """通过用户id初始化缓存"""
        self.data[user_id] = {
            "news_recommanded": [],
            "offset": {}
        }  # 清空已推荐的新闻

    def get_news_recommanded(self, user_id: int) -> list:
        """获取已对该用户推荐的新闻列表"""
        return self.data[user_id]["news_recommanded"]

    def add_to_news_recommanded(self, user_id: int, news_id: int) -> None:
        """添加新闻到已推荐的新闻列表中，避免重复推荐"""
        if news_id not in self.get_news_recommanded(user_id):  # 如果新闻未推荐过
            self.data[user_id]["news_recommanded"].append(news_id)

    def is_news_recommanded(self, user_id: int, news_id: int) -> bool:
        """判断新闻是否已经给该用户推荐过"""
        return news_id in self.get_news_recommanded(user_id)


"""
    def set_offset(self, user_id: int, category: str, offset: datetime):
        self.data[user_id]["offset"][category] = offset

    def has_offset(self, user_id: int, category: str):
        return category in self.data[user_id]["offset"]
"""

cache = Cache()  # 实例化缓存(single instance)


def get_intersted_category_percentage(db: Session, user_id: int) -> dict:
    """
        功能：获取用户兴趣类别的百分比
        返回示例: {'娱乐': 0.18, '体育': 0.22, '社会': 0.08, '财经': 0.04, '科技': 0.11, '军事': 0.36}
    """
    results = {}
    for view_history in curd.get_view_history_by_user_id(db, user_id, FETCH_VIEW_HISTORY_LIMIT):
        if view_history.duration < ANTI_NOICE_THRESHOLD_IN_MILLISECONDS:  # 过滤掉时长小于3秒的记录
            continue
        news = view_history.article
        if news.category not in results:  # 如果该类别未出现过
            results[news.category] = 1  # 初始化为1
        else:
            results[news.category] += 1  # 否则加1
    # print(results)
    count = sum(results.values())  # 计算总数
    for i in results:
        results[i] = round(results[i] / count, 2)  # 计算每个类别的百分比并保留两位小数
    # print(results)
    return results


def calc_target_news_num(db: Session, category_percentage: dict, total: int) -> list:
    """
        功能：将用户兴趣类别的百分比换算为目标新闻数量
        这里考虑了四舍五入导致的误差，会直接补偿在比例最大的类别上
        返回示例: [['军事', 7], ['体育', 4], ['娱乐', 4], ['科技', 2], ['社会', 2], ['财经', 1]]
    """
    category_percentage = sorted(
        category_percentage.items(), key=lambda x: x[1], reverse=True)  # 按照百分比排序
    count = 0  # 计数器
    result = []
    for category, percentage in category_percentage:
        category_news_num = int(round(total * percentage))  # 四舍五入取整
        count += category_news_num  # 计数器加上该类别的新闻数量
        #print(category, category_news_num)
        result.append([category, category_news_num])  # 添加结果到列表
    result[0][1] += total - count  # 补偿误差
    # print(result)
    return result


def recommend_news_by_category(db: Session, user: models.User, category: str, count: int) -> list:
    """根据类别推荐指定数量的新闻"""
    pool = []  # 候选样本池
    limit = int(count * FETCH_NEWS_FACTOR)  # 候选样本池大小
    assert limit >= count  # 确保样本池大小不小于目标数量
    offset = datetime.now()

    while len(pool) < limit:  # 由于要剔除已经推荐过的新闻，所有多次循环才能拿到指定数量的样本
        news_list = curd.get_news_by_category(
            db, category, offset, limit)  # 从数据库获取新闻
        offset = news_list[-1].created_at  # 更新偏移量

        for news in news_list:
            if cache.is_news_recommanded(user.id, news.id):  # 剔除已经推荐过的新闻
                continue
            pool.append(news)  # 添加到候选样本池

        if len(news_list) < limit:  # 数据库中没有更多的新闻
            # print("数据库中没有更多的新闻")  #debug
            break

    ######################################
    # TODO:
    #   进一步完善基于权重的推荐模型
    ######################################
    result = random.sample(pool, count)  # 随机抽取目标数量的新闻
    #print(category, result)
    for news in result:
        cache.add_to_news_recommanded(user.id, news.id)  # 标记为已推荐过
    return result


def recommand_news_by_user(db: Session, user: models.User, offset: int = 0, limit: int = RECOMMEND_RESULT_LIMIT) -> list:
    """按用户喜好推荐新闻"""
    result = []
    if not offset:  # 新会话
        cache.init_by_user_id(user.id)  # 初始化用户推荐缓存
    # 获取用户兴趣类别的百分比
    category_percentage = get_intersted_category_percentage(db, user.id)
    # 计算目标新闻数量
    target_news_num = calc_target_news_num(db, category_percentage, limit)
    for category, num in target_news_num:
        # 分别根据类别推荐新闻
        temp = recommend_news_by_category(db, user, category, num)
        result.extend(temp)

    return result


if __name__ == "__main__":
    ##############################################
    # DEBUG ONLY
    ##############################################
    from database import DBSession
    db = DBSession()
    user = curd.get_user(db, user_id=1)
    result = recommand_news_by_user(db, user)
    print(result)
    pass
