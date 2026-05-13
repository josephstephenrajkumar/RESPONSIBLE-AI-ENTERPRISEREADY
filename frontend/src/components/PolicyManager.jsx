import { useEffect, useState } from 'react'
import {
  activatePolicy,
  approvePolicy,
  createPolicy,
  deletePolicy,
  fetchPolicies,
  importHubPolicy,
  reloadPolicies,
  testPolicies,
  updatePolicy
} from '../api'
import GovernanceDashboard from './GovernanceDashboard'
import HubValidatorCatalog from './HubValidatorCatalog'
import PolicyApprovalModal from './PolicyApprovalModal'
import PolicyEditor from './PolicyEditor'
import PolicyTable from './PolicyTable'
import PolicyTestLab from './PolicyTestLab'

export default function PolicyManager() {
  const [policies, setPolicies] = useState([])
  const [editing, setEditing] = useState(null)
  const [approving, setApproving] = useState(null)
  const [reloadInfo, setReloadInfo] = useState(null)
  const [testResult, setTestResult] = useState(null)
  const [testing, setTesting] = useState(false)

  const refresh = async () => {
    const data = await fetchPolicies()
    setPolicies(data.policies || [])
  }

  useEffect(() => {
    refresh().catch(console.error)
  }, [])

  const submitPolicy = async (payload) => {
    let result
    if (editing) {
      result = await updatePolicy(editing.id, payload)
    } else if (payload.policy_kind === 'guardrails_hub') {
      result = await importHubPolicy(payload)
    } else {
      result = await createPolicy(payload)
    }
    setEditing(null)
    await refresh()
    return result?.policy
  }

  const disablePolicy = async (policy) => {
    await updatePolicy(policy.id, { enabled: !policy.enabled })
    await refresh()
  }

  const confirmApproval = async (policy) => {
    await approvePolicy(policy.id)
    setApproving(null)
    await refresh()
  }

  const runActivation = async (policy) => {
    await activatePolicy(policy.id)
    await refresh()
  }

  const runDelete = async (policy) => {
    await deletePolicy(policy.id)
    await refresh()
  }

  const runReload = async () => {
    const data = await reloadPolicies()
    setReloadInfo(data)
  }

  const runTest = async (message) => {
    setTesting(true)
    const data = await testPolicies(message)
    setTestResult(data)
    setTesting(false)
  }

  return (
    <div className="policy-manager-grid">
      <GovernanceDashboard policies={policies} reloadInfo={reloadInfo} onReload={runReload} />
      <HubValidatorCatalog onImportDraft={submitPolicy} />
      <PolicyEditor policy={editing} onSubmit={submitPolicy} onCancel={() => setEditing(null)} />
      <PolicyTable
        policies={policies}
        onEdit={setEditing}
        onDisable={disablePolicy}
        onApprove={setApproving}
        onActivate={runActivation}
        onDelete={runDelete}
      />
      <PolicyTestLab onRun={runTest} result={testResult} loading={testing} />
      <PolicyApprovalModal policy={approving} onClose={() => setApproving(null)} onConfirm={confirmApproval} />
    </div>
  )
}
