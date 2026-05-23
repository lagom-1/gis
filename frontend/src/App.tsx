import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import Submit from './pages/Submit'
import TaskPage from './pages/TaskPage'
import Conversations from './pages/Conversations'
import Gallery from './pages/Gallery'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="submit" element={<Submit />} />
        <Route path="tasks/:id" element={<TaskPage />} />
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
