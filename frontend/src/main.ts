import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import './style.css'
const router = createRouter({ history: createWebHashHistory(), routes: [
  { path: '/', redirect: '/plans' },
  { path: '/plans', component: () => import('./views/PlansPage.vue') }, { path: '/history', component: () => import('./views/HistoryPage.vue') },
  { path: '/overview', component: () => import('./views/OverviewPage.vue') }, { path: '/compare', component: () => import('./views/ComparePage.vue') },
  { path: '/heat', component: () => import('./views/HeatPage.vue') }, { path: '/recommend', component: () => import('./views/RecommendPage.vue') },
  { path: '/game', component: () => import('./views/GamePage.vue') }, { path: '/tasks', component: () => import('./views/TasksPage.vue') },
] })
createApp(App).use(router).mount('#app')
