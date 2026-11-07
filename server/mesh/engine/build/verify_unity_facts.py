"""Checks that every Class.member the Unity facts text relies on is in Unity's scripting reference index of the current
version (unity-index.js, https://docs.unity3d.com/ScriptReference/docdata/index.js), and that the names the facts call
obsolete are NOT in the current index (renamed ones) or are documented as obsolete.

    python verify_unity_facts.py unity-index.js unity-index-2022.3.js
"""
import json
import sys

MUST_EXIST = """Rigidbody.linearVelocity Rigidbody.angularVelocity Rigidbody.linearDamping Rigidbody.angularDamping
Rigidbody.AddForce Rigidbody.MovePosition Rigidbody.AddExplosionForce Rigidbody2D.linearVelocity Rigidbody2D.linearDamping
Object.FindFirstObjectByType Object.FindAnyObjectByType Object.FindObjectsByType Component.TryGetComponent
Component.CompareTag Awaitable.NextFrameAsync Awaitable.WaitForSecondsAsync Awaitable.FixedUpdateAsync
Awaitable.EndOfFrameAsync MonoBehaviour.destroyCancellationToken MonoBehaviour.StartCoroutine MonoBehaviour.StopCoroutine
Physics.Raycast Physics.CheckSphere Physics.OverlapSphereNonAlloc Physics.RaycastNonAlloc Physics.OverlapSphere
Physics.gravity Physics.simulationMode NavMeshAgent.SetDestination NavMeshAgent.pathPending
NavMeshAgent.remainingDistance NavMeshAgent.stoppingDistance NavMeshAgent.isStopped NavMeshAgent.ResetPath
NavMeshAgent.Warp NavMeshAgent.speed Animator.StringToHash Animator.SetFloat Animator.SetBool Animator.SetTrigger
Animator.CrossFade Animator.SetLayerWeight Animator.GetCurrentAnimatorStateInfo Animator.applyRootMotion
SceneManager.LoadScene SceneManager.LoadSceneAsync AsyncOperation.completed AsyncOperation.progress
AsyncOperation.allowSceneActivation Application.persistentDataPath Application.Quit JsonUtility.ToJson
JsonUtility.FromJson Time.timeScale Time.time Time.deltaTime Mathf.Abs Mathf.Sqrt WaitForSeconds.WaitForSeconds
WaitForFixedUpdate WaitUntil UIDocument.rootVisualElement VisualElement.schedule
VisualElement.style Button.clicked UnityEvent.AddListener ScriptableObject.CreateInstance
Object.DontDestroyOnLoad CreateAssetMenuAttribute.fileName CreateAssetMenuAttribute.menuName
SerializeField HeaderAttribute RangeAttribute MinAttribute Physics.Raycast RaycastHit.collider
Transform.position Camera.main""".split()
MUST_BE_GONE = "Rigidbody.velocity Rigidbody.drag Rigidbody.angularDrag Rigidbody2D.velocity Rigidbody2D.drag Physics.autoSimulation".split()


def load(path):
    t = open(path, encoding="utf-8").read()
    s, e = t.index("var pages") + len("var pages ="), t.index("var info")
    return {r[1] for r in json.loads(t[s:e].strip().rstrip(";")) if len(r) > 1}


def main(now_path, old_path):
    now, old = load(now_path), load(old_path)
    classes = {n.split(".")[0] for n in now}
    bad = []
    for n in MUST_EXIST:
        if "." not in n:
            ok = n in classes or any(c.split("<")[0] == n for c in classes)
        else:
            c, m = n.split(".", 1)
            ok = n in now or any(x.startswith(c + ".") and x.split(".", 1)[1].split("(")[0] == m for x in now) \
                or (c.endswith("Attribute") and False)
        if not ok:
            bad.append(("missing in Unity 6 index", n))
    for n in MUST_BE_GONE:
        if n in now:
            bad.append(("still in the Unity 6 index (facts call it obsolete)", n))
        if n not in old:
            bad.append(("was not in 2022.3 either", n))
    for tag, n in bad:
        print(tag, n)
    print(f"{len(MUST_EXIST)} names must exist, {len(MUST_BE_GONE)} must be gone: {len(bad)} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
