# SilkReel-01 · 江口缫丝坞

缫丝盆环状作业台。登录后看到的是沿汤池围成一圈的盆位，点盆登记汤温并改状态——不是侧栏双列表 CRUD。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Web API | Quart（异步 Flask 族）· Hypercorn |
| 结构 | `repositories.py` 仓储 + `services.py` 门槛，路由不直接拼 SQL |
| 数据 | SQLAlchemy 2 async · asyncpg · PostgreSQL 15 |
| 前端 | Preact 10 · Vite |
| 部署 | Docker Compose |

## 路径与端口

- 前端：http://localhost:4760
- API：http://localhost:8760
- PostgreSQL：localhost:6160

## 演示账号

| 用户名 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `123456` | 管理员 |
| `worker` | `123456` | 缫丝工 |

## 业务规则

- 盆状态不可标成「已缫完」，除非该盆**最近一条**汤温记录落在 **38～42℃**。规则在 `backend/app/services.py`。
- 管理员在「蒸汽总阀」专页设置同时允许处于**缫丝中**的口数上限（正整数）及是否启用。启用且已用口数等于上限时，再把浸茧（或已缫完）改成缫丝中会被挡下并返回中文错误；登记汤温、标已缫完都不经过总阀。停用后不限口数。
- 已用口数不是独立计数，而是在状态变更事务里 `SELECT … FOR UPDATE` 锁住总阀行后实时清点缫丝中盆数——专页数字始终等于库里盆数，两名工交叉改两口也不会超口。

## 快速启动

```bash
cd SilkReel/SilkReel-01
docker compose up --build
```
