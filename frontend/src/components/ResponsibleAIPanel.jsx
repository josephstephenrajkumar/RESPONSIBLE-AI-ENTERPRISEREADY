export default function ResponsibleAIPanel({ policy }) {
  return (
    <div className="panel">
      <h2>Responsible AI Policy</h2>
      {policy ? (
        <pre>{JSON.stringify(policy, null, 2)}</pre>
      ) : (
        <p>Loading policy configuration...</p>
      )}
    </div>
  )
}
