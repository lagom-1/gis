import { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './stores/authStore'
import Layout from './components/Layout'
import Home from './pages/Home'
import Login from './pages/Login'
import Register from './pages/Register'
import Submit from './pages/Submit'
import TaskPage from './pages/TaskPage'
import Profile from './pages/Profile'
import Conversations from './pages/Conversations'
import Gallery from './pages/Gallery'

export default function App() {
  const { token, fetchUser } = useAuthStore()

  // 应用启动时尝试恢复用户会话
  useEffect(() => {
    if (token) {
      fetchUser()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="login" element={<Login />} />
        <Route path="register" element={<Register />} />
        <Route path="submit" element={<Submit />} />
        <Route path="tasks/:id" element={<TaskPage />} />
        <Route path="profile" element={<Profile />} />
        <Route path="workspace" element={<Gallery />} />
        <Route path="workspace/:projectId" element={<Gallery />} />
        <Route path="gallery" element={<Gallery />} />
        <Route path="conversations" element={<Conversations />} />
        <Route path="conversations/:id" element={<Conversations />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
