"""Web 模块 - FastAPI + SSE 实时进度

最小骨架，不含业务逻辑，仅暴露通用接口：
  GET  /api/config           获取配置（projects、格式列表等）
  POST /api/generate         提交生成任务
  GET  /api/tasks/{id}       查询任务状态
  GET  /api/tasks/{id}/stream  SSE 实时进度
  GET  /api/tasks            历史任务
  GET  /api/tasks/{id}/download/{format}  下载输出文件

业务项目通过在主应用中 app.include_router() 附加自己的路由。
"""
