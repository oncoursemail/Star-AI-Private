"""The engine facts text (one core block per engine + topic parts picked by the question).

Where a real source exists, the signatures are written as placeholders and filled in at import from data files that
the build scripts generate from that source:
  g:Class.member in braces: Godot 4.7 engine API dump (`godot --dump-extension-api`)           data/godot_sigs.json
  l:module.func in braces: LOVE 11.5 API (love-api wiki index, names cross-checked with the running engine)  data/love_sigs.json
  lua:summary in braces: the Lua 5.4 reference manual's list of library functions                data/lua54_std.json
Unity and Unreal text is curated: Unity member names are checked against Unity's own scripting-reference index
(build/verify_unity_facts.py); Unreal has no public source to check against here (see docs/agents/engine-truth).
"""

# (family) -> {"core": text, "topics": [(regex, text), ...]}
FACTS = {
    "godot": {
        "core": (
            "Godot 4.x (GDScript 2.0), names checked against the engine's own API dump:\n"
            "- Syntax: `extends Node2D`, `class_name Foo`, `@export var speed := 200.0`, `@export_range(0, 100) var hp: int = 100`, "
            "`@onready var timer: Timer = $Timer`, `signal died`, `signal health_changed(current: int, maximum: int)`, "
            "emit with `died.emit()` / `health_changed.emit(hp, max_hp)`, connect with `other.died.connect(_on_died)` "
            "(a Callable, no strings), `await get_tree().create_timer(1.0).timeout`, `super()`, typed arrays `Array[int]`, "
            "lambdas `func(x): return x * 2`, `\"%d/%d\" % [a, b]`. Godot 3 names do not exist: yield, onready, export var, "
            "instance(), connect(\"sig\", self, \"fn\"), setget, KinematicBody2D, rand_range, OS.get_ticks_msec, "
            "linear2db, empty() (use is_empty()).\n"
            "- {g:PackedScene.instantiate}, then {g:Node.add_child}; remove with queue_free(). "
            "{g:SceneTree.create_timer}; scene change: get_tree().change_scene_to_file(\"res://x.tscn\").\n"
            "- Global math: randf_range(a, b), randi_range(a, b), clampf/clampi, lerpf, snappedf, move_toward, "
            "deg_to_rad, linear_to_db, wrapf, absf, signf, remap, is_equal_approx. {g:Time.get_ticks_msec}."),
        "topics": [
            (r"character|player|platformer|jump|gravity|coyote|move|walk|run\b|velocity|dash|top-?down|movement|3d",
             "- Movement: {g:CharacterBody2D.velocity} (a property you set), then `move_and_slide()` with NO arguments "
             "(returns bool); `is_on_floor()`; CharacterBody3D is the same. Gravity: "
             "`ProjectSettings.get_setting(\"physics/2d/default_gravity\")` (3d: physics/3d/default_gravity), "
             "`velocity.y += gravity * delta` in `_physics_process(delta: float)`. Input: {g:Input.get_axis}; "
             "{g:Input.get_vector}; `Input.is_action_just_pressed(\"jump\")`; timers (coyote, buffer) are floats "
             "decremented by delta and reset when used."),
            (r"signal|event|health|damage|died|death|observer|emit|connect|component",
             "- Signals: declare `signal died`, emit `died.emit()`, connect `health.died.connect(queue_free)` or "
             "`.connect(_on_died)`; one-shot: `.connect(f, CONNECT_ONE_SHOT)`; `is_connected(callable)`. A guard flag "
             "(`var is_dead := false`) keeps `died` firing once. {g:Object.has_method}; {g:Object.set_meta}."),
            (r"timer|cooldown|delay|wait|tween|animat|fade|lerp|smooth|ease|interval",
             "- Timers: {g:Timer.start} (wait_time, one_shot, autostart; signal {g:Timer.timeout}); "
             "`await get_tree().create_timer(sec).timeout`. Tweens: `var tw := create_tween()`; {g:Tween.tween_property}; "
             "{g:Tween.tween_callback}; {g:Tween.set_parallel}; {g:Tween.set_trans}; `tw.finished`; "
             "`.set_ease(Tween.EASE_OUT)`; `.set_loops(0)` loops forever. No Tween node, no interpolate_property."),
            (r"save|load|settings|config|persist|json|file|user://|inventory",
             "- Files: `user://` is the writable folder, `res://` is read-only when exported. {g:FileAccess.open}; null on "
             "failure, so check `FileAccess.get_open_error()`; {g:FileAccess.store_string}; {g:FileAccess.get_as_text}; "
             "{g:JSON.stringify}; {g:JSON.parse_string} (returns null on bad JSON); {g:ConfigFile.set_value}; "
             "{g:ConfigFile.get_value}; `cfg.load(path)` returns Error (ERR_FILE_NOT_FOUND = 7); `cfg.save(path)`. "
             "{g:DirAccess.make_dir_recursive_absolute}. Audio bus volume: {g:AudioServer.set_bus_volume_db} with "
             "`linear_to_db(v)`; {g:AudioServer.get_bus_index}; fullscreen: {g:DisplayServer.window_set_mode} with "
             "DisplayServer.WINDOW_MODE_FULLSCREEN / WINDOW_MODE_WINDOWED."),
            (r"ui\b|button|label|menu|hud|control|health ?bar|progress|slider|text|panel|dialog",
             "- UI: Control nodes; {g:Button.pressed}; `label.text = \"x\"`; {g:ProgressBar.value}; "
             "{g:Range.value_changed}; {g:LineEdit.text_submitted}; {g:Control.set_anchors_preset} "
             "(Control.PRESET_FULL_RECT); `add_theme_color_override(\"font_color\", c)`; `visible`; "
             "{g:BaseButton.toggled}. Rich text: `bbcode_enabled = true`, `append_text()`."),
            (r"area|collision|hit|overlap|ray|trigger|pickup|coin|bullet|projectile|detect|physics",
             "- Physics: {g:Area2D.body_entered}; {g:Area2D.area_entered}; `get_overlapping_bodies()`; "
             "{g:RayCast2D.is_colliding}; {g:RayCast2D.get_collider}; "
             "RayCast2D.force_raycast_update(); layers: {g:CollisionObject2D.set_collision_layer_value}; "
             "{g:PhysicsRayQueryParameters2D.create} then "
             "`get_world_2d().direct_space_state.intersect_ray(query)` returns a Dictionary (empty = no hit; keys position, "
             "normal, collider). {g:RigidBody2D.apply_central_impulse}; `linear_velocity`. Change physics state in "
             "`set_deferred(\"disabled\", true)` inside signals."),
            (r"anim|sprite|frame",
             "- Animation: {g:AnimationPlayer.play}; {g:AnimationPlayer.animation_finished}; "
             "{g:AnimatedSprite2D.play}; {g:AnimatedSprite2D.animation_finished}; `flip_h`; AnimationTree state machine: "
             "`$AnimationTree[\"parameters/playback\"].travel(\"run\")`."),
            (r"audio|sound|music|volume|sfx",
             "- Audio: {g:AudioStreamPlayer.play}; `stream`, `volume_db`, `bus`, signal {g:AudioStreamPlayer.finished}; "
             "{g:AudioServer.set_bus_volume_db} with `linear_to_db(0.5)`; {g:AudioServer.set_bus_mute}."),
            (r"navigation|pathfind|nav\b|agent|chase|follow|patrol|enemy|ai\b",
             "- Navigation: {g:NavigationAgent2D.target_position} (property, not set_target_location); "
             "{g:NavigationAgent2D.get_next_path_position}; {g:NavigationAgent2D.is_navigation_finished}; "
             "agent.velocity_computed signal for avoidance; NavigationServer2D. Chase: "
             "`velocity = global_position.direction_to(target.global_position) * speed`."),
            (r"tilemap|tile|grid|map\b|cell",
             "- Tiles: TileMapLayer nodes (Godot 4.3+; TileMap is deprecated): {g:TileMapLayer.set_cell}; "
             "{g:TileMapLayer.local_to_map}; {g:TileMapLayer.map_to_local}; {g:TileMapLayer.erase_cell}; "
             "{g:TileMapLayer.get_used_cells}. Grid math: Vector2i (ints, x/y), `rows[y][x]` for a String array."),
            (r"multiplayer|network|rpc|server|client|peer|enet",
             "- Multiplayer: `@rpc(\"any_peer\", \"call_local\", \"reliable\") func hit(): ...`; call with `hit.rpc()` / "
             "`hit.rpc_id(1)`; {g:MultiplayerAPI.is_server}; `multiplayer.get_unique_id()`; "
             "{g:ENetMultiplayerPeer.create_server}; `multiplayer.multiplayer_peer = peer`; "
             "MultiplayerSpawner / MultiplayerSynchronizer nodes."),
            (r"string|array|dictionary|split|parse|text|sort|duration|format|digit|chunk|rank|word",
             "- Strings/collections: {g:String.split}; {g:String.pad_zeros}; {g:String.lpad}; {g:String.substr}; "
             "{g:String.strip_edges}; {g:String.to_int}; {g:String.is_valid_int} (also accepts a leading + or -); "
             "{g:Array.sort_custom} (comparator returns bool a-before-b; not stable); {g:Array.filter}; "
             "{g:Array.map}; {g:Array.slice}; {g:Array.pick_random}; {g:Dictionary.get}; `dict.has(k)`; `dict.keys()`; "
             "Array is a reference type (duplicate() copies); `int / int` is integer division (use float()); `%` on "
             "ints is the remainder."),
            (r"camera|shake|zoom|view",
             "- Camera: {g:Camera2D.make_current}; `zoom` (Vector2), `position_smoothing_enabled`, `offset` for shake; "
             "Camera3D.project_ray_origin / project_ray_normal for mouse picking."),
            (r"shader|material|visual|particle|vfx|effect",
             "- Visuals: `shader_type canvas_item;` with `uniform float x : hint_range(0.0, 1.0);`; "
             "{g:ShaderMaterial.set_shader_parameter}; GPUParticles2D `emitting`, `restart()`; `modulate` colour."),
            (r"scene|spawn|instance|wave|enemy|prefab|group|autoload|singleton",
             "- Scenes: `@export var enemy_scene: PackedScene`; `var e := enemy_scene.instantiate()`; set position after "
             "`add_child(e)` if you use global_position; groups: `add_to_group(\"enemies\")`, "
             "{g:SceneTree.get_nodes_in_group}, `get_tree().call_group(...)`; `tree_exited` signal to count removals; "
             "autoloads are global names set in Project Settings > Globals (the node's name is the variable)."),
        ],
    },
    "unity": {
        "core": (
            "Unity 6 (6000.x) API facts (member names checked against Unity's scripting reference):\n"
            "- Rigidbody: `rb.linearVelocity`, `rb.angularVelocity`, `rb.linearDamping`, `rb.angularDamping` "
            "(velocity, drag, angularDrag are obsolete; Rigidbody2D the same). Read input in Update into fields, apply "
            "physics in FixedUpdate (consume the jump flag there). `rb.AddForce(v, ForceMode.Impulse)`, `rb.MovePosition`. "
            "Jump speed for height h: sqrt(2 * g * h) with g = Mathf.Abs(Physics.gravity.y).\n"
            "- Lookups: FindFirstObjectByType<T>(), FindAnyObjectByType<T>(), FindObjectsByType<T>(FindObjectsSortMode.None) "
            "(FindObjectOfType/FindObjectsOfType are obsolete). Cache in Awake/Start, never per frame; "
            "`TryGetComponent(out T c)`; `CompareTag(\"Player\")` not `tag ==`.\n"
            "- Serialization: `[SerializeField] private float speed = 5f;` (not public), `[Header]`, `[Range(0,1)]`, "
            "`[Min(0)]`; Inspector-hookable events are UnityEngine.Events.UnityEvent / UnityEvent<int,int> (a C# "
            "`event Action` is NOT visible in the Inspector). Unsubscribe in OnDisable. Arrays of classes need "
            "[System.Serializable] and each element created (`new Slot()`). `?.` / `??` skip Unity's null check: use "
            "`if (x != null)`.\n"
            "- Input System package is the default in Unity 6: `using UnityEngine.InputSystem;` "
            "`Keyboard.current.spaceKey.wasPressedThisFrame`, `InputAction.ReadValue<Vector2>()`, "
            "`action.performed += ctx => ...`, `action.Enable()`; the legacy `Input.GetAxis/GetKey` throws "
            "InvalidOperationException when Active Input Handling is Input System only. "
            "`using System;` + `using UnityEngine;` makes `Random` ambiguous: write UnityEngine.Random.Range."),
        "topics": [
            (r"pool|spawn|bullet|projectile|instantiate",
             "- Pooling: `using UnityEngine.Pool;` `new ObjectPool<T>(createFunc, actionOnGet, actionOnRelease, "
             "actionOnDestroy, collectionCheck: true, defaultCapacity: 10, maxSize: 100)`; `pool.Get()`; "
             "`pool.Release(T)` takes the pooled TYPE you created (the Projectile component), never its GameObject; "
             "activate in actionOnGet, deactivate in actionOnRelease; a second Release of the same instance throws "
             "(guard with a flag). Reset `rb.linearVelocity = Vector3.zero`, `rb.angularVelocity`, position, rotation on "
             "Get. Fire rate: `if (Time.time >= nextShot) { nextShot = Time.time + 1f / rate; }`. Lifetime: a timer "
             "that calls Release, not Destroy."),
            (r"await|async|awaitable|coroutine|delay|wait|cooldown",
             "- Async: `await Awaitable.NextFrameAsync();` `await Awaitable.WaitForSecondsAsync(2f, destroyCancellationToken);` "
             "`await Awaitable.FixedUpdateAsync();` (UnityEngine namespace, methods return Awaitable / Awaitable<T>, "
             "`destroyCancellationToken` is a MonoBehaviour property; wrap in try/catch OperationCanceledException). "
             "Coroutines: `yield return new WaitForSeconds(t)` (cache it), WaitForFixedUpdate, WaitUntil, "
             "`StartCoroutine(Routine())`, `StopCoroutine(handle)`."),
            (r"ui toolkit|uielements|uxml|uss|visualelement|uidocument|hud|ui\b|button|label|canvas|textmeshpro|tmp",
             "- UI Toolkit: `using UnityEngine.UIElements;` `[SerializeField] UIDocument doc;` "
             "`var root = doc.rootVisualElement;` `root.Q<Label>(\"score\").text = \"1\";` `root.Q<Button>(\"play\").clicked += OnPlay;` "
             "`element.style.display = DisplayStyle.None;` `element.RegisterCallback<ClickEvent>(e => ...)`; query in "
             "OnEnable (not Awake); `schedule.Execute(() => ...).Every(100)`. uGUI: `using UnityEngine.UI;` (Text, Button, "
             "Slider, Image: `image.fillAmount`), TextMeshPro `using TMPro;` TMP_Text / TextMeshProUGUI `.text`."),
            (r"navmesh|nav mesh|patrol|agent|chase|enemy|ai\b|waypoint",
             "- NavMeshAgent (`using UnityEngine.AI;`): `agent.SetDestination(p)`, `agent.pathPending`, "
             "`agent.remainingDistance <= agent.stoppingDistance`, `agent.speed`, `agent.isStopped`, `agent.ResetPath()`, "
             "`agent.Warp(p)`. Advance a waypoint only when `!agent.pathPending && agent.remainingDistance <= "
             "agent.stoppingDistance`. Line of sight: `Physics.Raycast(eye, dir, out RaycastHit hit, range, mask, "
             "QueryTriggerInteraction.Ignore)` with a mask that includes BOTH obstacles and the player, then check "
             "`hit.collider.CompareTag(\"Player\")`."),
            (r"save|load|json|persist|file|settings|serialize|playerprefs",
             "- Save/load: `Application.persistentDataPath` + `Path.Combine`; `JsonUtility.ToJson(obj, true)` / "
             "`JsonUtility.FromJson<T>(json)` (T is a [Serializable] class with public or [SerializeField] fields; "
             "List<T> yes, Dictionary no; invalid JSON throws ArgumentException); safe write: `File.WriteAllText(tmp, json)` "
             "then `File.Replace(tmp, path, null)` when path exists, else `File.Move`; Load returns new default data when "
             "the file is missing or corrupt (try/catch)."),
            (r"cinemachine|camera|follow|shake|impulse|virtual",
             "- Cinemachine 3: `using Unity.Cinemachine;` components CinemachineCamera (not CinemachineVirtualCamera), "
             "CinemachineBrain, CinemachineConfiner2D / CinemachineConfiner3D, CinemachineImpulseSource "
             "(`GenerateImpulse()`), CinemachineFollow, CinemachineRotationComposer; `cam.Follow = t; cam.LookAt = t;` "
             "`cam.Priority.Value = 20` (PrioritySettings, not an int). Cinemachine 2 used `using Cinemachine;`. "
             "Camera.main is cached by Unity but still cache it."),
            (r"physics|raycast|overlap|explosion|collider|trigger|ground|sphere|layermask|hit",
             "- Physics queries: `Physics.Raycast(origin, dir, out RaycastHit hit, maxDistance, layerMask, "
             "QueryTriggerInteraction.Ignore)`, `Physics.CheckSphere(pos, r, mask)`, "
             "`Physics.OverlapSphereNonAlloc(pos, r, Collider[] buffer, mask)` returns the count (reuse the buffer; "
             "OverlapSphere allocates), `Physics.RaycastNonAlloc`, `rb.AddExplosionForce(force, pos, radius, "
             "upwardsModifier, ForceMode.Impulse)`. LayerMask fields: `[SerializeField] private LayerMask groundMask;`. "
             "OnCollisionEnter(Collision c) / OnTriggerEnter(Collider other) need a Rigidbody on one object."),
            (r"animator|animation|blend|state machine|layer|parameter|channel",
             "- Animator: cache hashes `static readonly int Speed = Animator.StringToHash(\"Speed\");` "
             "`anim.SetFloat(Speed, v, dampTime, Time.deltaTime)`, `SetBool`, `SetTrigger`, `anim.CrossFade(\"Run\", 0.1f)`, "
             "`anim.SetLayerWeight(layer, w)`, `anim.GetCurrentAnimatorStateInfo(layer).normalizedTime`, "
             "`anim.applyRootMotion`."),
            (r"scriptableobject|scriptable|inventory|item|event channel|data",
             "- ScriptableObject: `[CreateAssetMenu(fileName = \"NewItem\", menuName = \"Game/Item\")] public class "
             "ItemDefinition : ScriptableObject`; share by reference (compare references, not names); runtime state "
             "belongs in the MonoBehaviour/Serializable slot class, not the asset. Initialise Inspector-visible arrays in "
             "Awake/Reset, never in a field initialiser of a MonoBehaviour constructor."),
            (r"scene|load|menu|level|additive",
             "- Scenes: `SceneManager.LoadScene(\"Name\")`, `SceneManager.LoadSceneAsync(name, LoadSceneMode.Additive)` "
             "(returns AsyncOperation; `op.completed`, `op.progress` stops at 0.9 with allowSceneActivation=false); "
             "`DontDestroyOnLoad(gameObject)`; `Application.Quit()`; `Time.timeScale`."),
        ],
    },
    "unreal": {
        "core": (
            "Unreal Engine 5.x C++ facts (from Epic's public API docs; not compiler-checked):\n"
            "- Header: `#pragma once`, `#include \"CoreMinimal.h\"`, base class header, then LAST `#include \"Foo.generated.h\"`; "
            "`UCLASS(Blueprintable, BlueprintType)`, `class MYGAME_API AFoo : public AActor { GENERATED_BODY() ...`. Prefixes: "
            "A actors, U UObjects/components, F structs, E enums, I interfaces. UObject pointers that must stay alive are "
            "`UPROPERTY()` members, in UE5 `TObjectPtr<UStaticMeshComponent>`; create objects with "
            "`CreateDefaultSubobject<T>(TEXT(\"Name\"))` in the constructor only, `NewObject<T>(Outer)` at runtime, "
            "`GetWorld()->SpawnActor<AFoo>(Class, Transform, Params)`; never `new` a UObject.\n"
            "- Specifiers: `UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = \"X\", meta = (ClampMin = \"0\"))`, "
            "`UFUNCTION(BlueprintCallable, Category = \"X\")`, `BlueprintPure`, `BlueprintImplementableEvent`, "
            "`BlueprintNativeEvent` (implement `Foo_Implementation`). Components attach with "
            "`Mesh->SetupAttachment(Root)` (SetRootComponent / `RootComponent = Root`). `PrimaryActorTick.bCanEverTick = true;` "
            "`virtual void BeginPlay() override { Super::BeginPlay(); }`, `Tick(float DeltaTime)`.\n"
            "- Delegates: `DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnHealthChanged, float, NewHealth, float, Delta);` "
            "declared above the UCLASS, member `UPROPERTY(BlueprintAssignable) FOnHealthChanged OnHealthChanged;`, "
            "`OnHealthChanged.Broadcast(a, b)`. `AddDynamic(this, &UFoo::Handler)` needs a `UFUNCTION()` handler with exactly "
            "the delegate's signature, bound in BeginPlay (not the constructor). OnTakeAnyDamage handler: "
            "`void HandleDamage(AActor* DamagedActor, float Damage, const UDamageType* DamageType, AController* "
            "InstigatedBy, AActor* DamageCauser)`.\n"
            "- Strings: FString (`FString::Printf(TEXT(\"%s %d\"), *Name, N)`), FName, FText; `UE_LOG(LogTemp, Warning, "
            "TEXT(\"...\"))`; containers TArray (Add, Emplace, RemoveAt, Num, Contains, FindByPredicate), TMap "
            "(Add, Find returns a pointer or nullptr, FindOrAdd, Contains), TSet; check pointers with `IsValid(Ptr)`; "
            "`Cast<T>(Obj)`."),
        "topics": [
            (r"enhanced input|input action|input mapping|inputaction|mapping context|character|move|look|jump|third.person|player",
             "- Enhanced Input: Build.cs needs \"EnhancedInput\"; includes \"EnhancedInputComponent.h\", "
             "\"EnhancedInputSubsystems.h\", \"InputActionValue.h\". `UPROPERTY(EditAnywhere) TObjectPtr<UInputMappingContext> "
             "DefaultContext; TObjectPtr<UInputAction> MoveAction;` In BeginPlay (or PossessedBy): `if (APlayerController* PC "
             "= Cast<APlayerController>(GetController())) if (auto* Sub = ULocalPlayer::GetSubsystem"
             "<UEnhancedInputLocalPlayerSubsystem>(PC->GetLocalPlayer())) Sub->AddMappingContext(DefaultContext, 0);` "
             "SetupPlayerInputComponent: `if (auto* EIC = Cast<UEnhancedInputComponent>(PlayerInputComponent)) "
             "EIC->BindAction(MoveAction, ETriggerEvent::Triggered, this, &AHero::Move);` handlers take "
             "`const FInputActionValue& Value`; `const FVector2D V = Value.Get<FVector2D>();` Move by yaw only: "
             "`const FRotator Yaw(0.f, GetControlRotation().Yaw, 0.f); AddMovementInput(FRotationMatrix(Yaw)."
             "GetUnitAxis(EAxis::X), V.Y);` Look: AddControllerYawInput / AddControllerPitchInput. Jump: "
             "BindAction(JumpAction, ETriggerEvent::Started, this, &ACharacter::Jump) and Completed -> StopJumping. "
             "Spring arm: `CreateDefaultSubobject<USpringArmComponent>`, `bUsePawnControlRotation = true`; character "
             "faces movement: `GetCharacterMovement()->bOrientRotationToMovement = true;`. Legacy BindAxis/BindAction "
             "with strings is the old input system."),
            (r"overlap|pickup|coin|collect|sphere|collision|trigger|begin ?overlap|hit",
             "- Overlap: `UPROPERTY(VisibleAnywhere) TObjectPtr<USphereComponent> Sphere;` "
             "`UFUNCTION() void OnOverlap(UPrimitiveComponent* OverlappedComp, AActor* OtherActor, UPrimitiveComponent* "
             "OtherComp, int32 OtherBodyIndex, bool bFromSweep, const FHitResult& SweepResult);` bind "
             "`Sphere->OnComponentBeginOverlap.AddDynamic(this, &ACoin::OnOverlap);` in the constructor or "
             "PostInitializeComponents/BeginPlay; Sphere->SetCollisionProfileName(TEXT(\"OverlapAllDynamic\")), "
             "`SetGenerateOverlapEvents(true)`; mesh `SetCollisionEnabled(ECollisionEnabled::NoCollision)`. Server "
             "decides: `if (!HasAuthority()) return;` then `if (APawn* P = Cast<APawn>(OtherActor)) if "
             "(P->IsPlayerControlled())`; `P->GetPlayerState()->SetScore(P->GetPlayerState()->GetScore() + Value)`; "
             "`UGameplayStatics::PlaySoundAtLocation(this, Sound, GetActorLocation())`; `Destroy()`. Rotation: "
             "`AddActorLocalRotation(FRotator(0, 90 * DeltaTime, 0))` in Tick."),
            (r"replicat|multiplayer|network|server|rpc|authority|onrep|dorep",
             "- Replication: `bReplicates = true;` (actor constructor; components `SetIsReplicatedByDefault(true)`); "
             "`UPROPERTY(ReplicatedUsing = OnRep_Health) float Health;` `UFUNCTION() void OnRep_Health();` and "
             "`virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;` with "
             "`#include \"Net/UnrealNetwork.h\"`, body `Super::GetLifetimeReplicatedProps(OutLifetimeProps); "
             "DOREPLIFETIME(AFoo, Health);`. RPC: `UFUNCTION(Server, Reliable) void ServerFire();` implemented as "
             "`void AFoo::ServerFire_Implementation()` (add WithValidation only if you write `_Validate`); `Client`, "
             "`NetMulticast` likewise. `HasAuthority()`, `GetLocalRole()`, `IsLocallyControlled()`."),
            (r"line ?trace|raycast|hitscan|weapon|fire|shoot|trace|fhitresult",
             "- Traces: `FHitResult Hit; FCollisionQueryParams Params; Params.AddIgnoredActor(this); "
             "const bool bHit = GetWorld()->LineTraceSingleByChannel(Hit, Start, End, ECC_Visibility, Params);` "
             "`Hit.GetActor()`, `Hit.ImpactPoint`, `Hit.ImpactNormal`, `Hit.bBlockingHit`; camera view: "
             "`PC->GetPlayerViewPoint(Loc, Rot)`; `UGameplayStatics::ApplyPointDamage(Hit.GetActor(), Damage, "
             "Dir, Hit, PC, this, UDamageType::StaticClass())`; ApplyDamage(Actor, Damage, InstigatorController, "
             "DamageCauser, DamageTypeClass); `DrawDebugLine` needs \"DrawDebugHelpers.h\". Fire rate: "
             "`GetWorld()->GetTimeSeconds()` against a next-fire time or `GetWorldTimerManager().SetTimer(Handle, "
             "this, &AGun::Fire, Interval, true)`; ClearTimer(Handle)."),
            (r"subsystem|save game|savegame|slot|singleton|game instance|world subsystem",
             "- Subsystems: `UCLASS() class UFooSubsystem : public UGameInstanceSubsystem` (also UWorldSubsystem, "
             "ULocalPlayerSubsystem, UEngineSubsystem); `virtual void Initialize(FSubsystemCollectionBase& Collection) "
             "override; virtual void Deinitialize() override;` access: `GetGameInstance()->GetSubsystem<UFooSubsystem>()`. "
             "Save: `USaveGame` subclass with UPROPERTY fields; `UGameplayStatics::CreateSaveGameObject(USaveGameClass)`, "
             "`SaveGameToSlot(Obj, SlotName, UserIndex)`, `LoadGameFromSlot`, `DoesSaveGameExist`, "
             "`AsyncSaveGameToSlot` with a delegate."),
            (r"gameplay ability|\bgas\b|attribute ?set|ability system|gameplayeffect|gameplay effect|gameplaytag",
             "- GAS: Build.cs modules \"GameplayAbilities\", \"GameplayTags\", \"GameplayTasks\"; "
             "`#include \"AbilitySystemComponent.h\"`, `\"AttributeSet.h\"`; `UCLASS() class UMyAttributes : public UAttributeSet`; "
             "`UPROPERTY(BlueprintReadOnly, ReplicatedUsing = OnRep_Health) FGameplayAttributeData Health;` with "
             "`ATTRIBUTE_ACCESSORS(UMyAttributes, Health)` (macro you define from GAMEPLAYATTRIBUTE_PROPERTY_GETTER / "
             "VALUE_GETTER / VALUE_SETTER / VALUE_INITTER), `GAMEPLAYATTRIBUTE_REPNOTIFY(UMyAttributes, Health, OldHealth)` in "
             "OnRep, `PreAttributeChange(const FGameplayAttribute&, float& NewValue)` to clamp; the ASC "
             "`UAbilitySystemComponent` on the character implements IAbilitySystemInterface "
             "(`GetAbilitySystemComponent()`); `InitAbilityActorInfo(Owner, Avatar)`; `GiveAbility(FGameplayAbilitySpec(Class, 1))`."),
            (r"data ?asset|soft|async|load|stream|primary|asset manager|thread|parallel|task",
             "- Assets/async: `UCLASS() class UWeaponData : public UPrimaryDataAsset` with UPROPERTY(EditAnywhere) "
             "fields; `TSoftObjectPtr<UTexture2D>` / `TSoftClassPtr<AActor>`; async load: `FStreamableManager& SM = "
             "UAssetManager::GetStreamableManager(); SM.RequestAsyncLoad(Soft.ToSoftObjectPath(), FStreamableDelegate::"
             "CreateUObject(this, &UFoo::OnLoaded));` sync `Soft.LoadSynchronous()`. Threads: "
             "`Async(EAsyncExecution::ThreadPool, [..]() {...})`, `AsyncTask(ENamedThreads::GameThread, [..]() {...})` to "
             "return to the game thread, `ParallelFor(Num, [&](int32 i) {...})`; never touch UObjects off the game thread."),
            (r"widget|umg|hud|userwidget|ui\b",
             "- UMG: `UCLASS() class UHud : public UUserWidget`; `UPROPERTY(meta = (BindWidget)) TObjectPtr<UTextBlock> "
             "ScoreText;` (name must match the widget in the Blueprint); `virtual void NativeConstruct() override;` "
             "`ScoreText->SetText(FText::AsNumber(Score))`; `CreateWidget<UHud>(PC, HudClass)->AddToViewport()`; "
             "Build.cs \"UMG\"."),
        ],
    },
    "love": {
        "core": (
            "LÖVE 11.x (LuaJIT 2.1, Lua 5.1 syntax; names checked against the LÖVE 11.5 API and the running engine):\n"
            "- Callbacks: love.load(arg), love.update(dt), love.draw(), love.keypressed(key, scancode, isrepeat), "
            "love.keyreleased(key, scancode), love.mousepressed(x, y, button, istouch, presses), love.mousemoved(x, y, dx, dy, "
            "istouch), love.textinput(text), love.resize(w, h), love.quit(). Quit: love.event.quit(). Keys are strings "
            "(\"space\", \"return\", \"escape\", \"left\", \"w\"); mouse buttons are numbers (1 = left).\n"
            "- Colours are 0-1 floats since 11.0: love.graphics.setColor(1, 0.5, 0, 1) (never 0-255). {l:graphics.rectangle}; "
            "{l:graphics.circle}; {l:graphics.print}; {l:graphics.printf}; {l:graphics.draw}; love.graphics.setBackgroundColor(r, g, b); "
            "love.graphics.getWidth() / getHeight() / getDimensions(); {l:graphics.newFont}.\n"
            "- Input polling: love.keyboard.isDown(\"a\", \"left\"); love.mouse.isDown(1); love.mouse.getPosition() returns x, y. "
            "{l:timer.getTime}; love.timer.getFPS(); {l:math.random} (also love.math.newRandomGenerator(seed)). "
            "Scale every movement by dt; normalise diagonal movement (divide by the length when both axes are pressed). "
            "Remove items from a table while looping backwards: `for i = #t, 1, -1 do ... table.remove(t, i) end`.\n"
            "- Lua here is LuaJIT: no `//` operator, no integer type, no `&`/`|` operators (use the `bit` library: bit.band, "
            "bit.bor, bit.lshift), `unpack` is a global, math.atan2 exists (math.atan with two arguments also works), "
            "`goto` exists. love.filesystem.exists/isFile/isDirectory/getSize are deprecated (gone in LÖVE 12): use {l:filesystem.getInfo}. `utf8` is not a global: `local utf8 = require(\"utf8\")`."),
        "topics": [
            (r"physics|world|body|fixture|box2d|collision|contact|gravity",
             "- love.physics (Box2D, meters: love.physics.setMeter(64)): {l:physics.newWorld}; {l:physics.newBody}; "
             "{l:physics.newRectangleShape}; {l:physics.newCircleShape}; {l:physics.newFixture}; `world:update(dt)`; "
             "`world:setCallbacks(beginContact, endContact, preSolve, postSolve)`; `body:applyLinearImpulse(ix, iy)`; "
             "`body:getPosition()`; `fixture:setUserData(x)`; `fixture:getBody()`."),
            (r"shader|glsl|effect|pixel|post",
             "- Shaders: {l:graphics.newShader}; pixel shader: `vec4 effect(vec4 color, Image tex, vec2 texture_coords, vec2 "
             "screen_coords) { vec4 px = Texel(tex, texture_coords); return px * color; }` (GLSL ES, `Texel` not texture2D); "
             "`extern float time;` + `shader:send(\"time\", t)`; use with love.graphics.setShader(shader) ... setShader()."),
            (r"canvas|render|offscreen|scale|resolution|pixel art|pixelart|filter|crisp|zoom",
             "- Canvas/scaling: {l:graphics.newCanvas}; {l:graphics.setCanvas}; `love.graphics.setCanvas()` to return; "
             "love.graphics.setDefaultFilter(\"nearest\", \"nearest\") BEFORE loading images for crisp pixels; "
             "love.graphics.push() / translate / scale / pop(); love.window.setMode(w, h, {resizable = true})."),
            (r"quad|sprite|spritesheet|batch|animation|image|tile|atlas",
             "- Images: {l:graphics.newImage}; {l:graphics.newQuad}; `image:getDimensions()` returns w, h; "
             "draw a quad: love.graphics.draw(image, quad, x, y, r, sx, sy, ox, oy); {l:graphics.newSpriteBatch}; "
             "animation = quads list + a timer advanced by dt."),
            (r"audio|sound|music|source|sfx|volume",
             "- Audio: {l:audio.newSource}; `src:play()`, `src:stop()`, `src:setLooping(true)`, `src:setVolume(0..1)`; "
             "static sources for short effects, \"stream\" for music; `src:clone()` to overlap plays; love.audio.setVolume."),
            (r"save|load|file|filesystem|persist|settings|json|serializ",
             "- Files: love.filesystem writes only inside the save directory: {l:filesystem.write}; {l:filesystem.read}; "
             "{l:filesystem.getInfo} (nil when missing, else a table with type and size); love.filesystem.createDirectory; "
             "love.filesystem.load(\"file.lua\")() runs a Lua file; there is no json library built in (write a small "
             "serializer or use love.data.encode)."),
            (r"state|menu|pause|scene|game ?over|machine",
             "- States: a table per state with optional enter/leave/update/draw/keypressed; a `switch(name, ...)` "
             "function calls leave on the old state and enter on the new one, passing arguments; love.update/draw/"
             "keypressed forward to the current state with nil-checks. Pause = do not call the play state's update "
             "(and do not advance timers from wall-clock time: accumulate dt). Use keypressed for discrete actions, "
             "isDown for held keys."),
            (r"window|fullscreen|resize|icon|title|vsync|conf",
             "- Window: conf.lua `function love.conf(t) t.window.title = \"x\"; t.window.width = 800; t.window.height = 600; "
             "t.version = \"11.5\" end`; {l:window.setMode}; love.window.setFullscreen(true); love.window.setTitle(\"x\")."),
            (r"gamepad|joystick|controller|touch|mobile",
             "- Gamepad: love.joystickadded(joystick); `joystick:isGamepadDown(\"a\")`, `joystick:getGamepadAxis(\"leftx\")` "
             "(-1..1; apply a dead zone); love.gamepadpressed(joystick, button); touch: love.touchpressed(id, x, y, dx, dy, pressure)."),
        ],
    },
    "lua": {
        "core": (
            "Plain Lua 5.4 (no Roblox/Luau, no LÖVE). The standard library is exactly:\n"
            "{lua:summary}\n"
            "- Not in Lua: string.split / trim / startswith, table.find / count / clone / clear / isEmpty, math.clamp / round / sign, "
            "`continue`, `+=`, `!=` (use ~=), `unpack` (use table.unpack), `loadstring` (use load), `bit32`, math.pow / "
            "atan2 / cosh / log10 / ldexp (removed in 5.4: use x^y, math.atan(y, x), math.log(x, 10)), wait, task, game, "
            "Instance, Vector3, typeof. Split with `for w in s:gmatch(\"[^,]+\") do`, trim with `s:match(\"^%s*(.-)%s*$\")`; "
            "skip an iteration with `goto continue` and a `::continue::` label at the end of the loop body.\n"
            "- Numbers: `/` always gives a float (`10 / 2` prints 5.0), `//` is floor division (integers stay integers), "
            "`%` follows the sign of the divisor, `math.floor` returns an integer, `math.tointeger(x)`, `math.type(x)`, "
            "`3 == 3.0` is true but `tostring` differs (\"3\" vs \"3.0\"); `string.format(\"%d\", 3.5)` is an error "
            "(\"number has no integer representation\"); integers wrap on overflow; bitwise `& | ~ << >>` and `~x`.\n"
            "- I/O: `for line in io.lines() do` reads stdin lines (`io.lines` is an iterator factory: never `ipairs(io.lines())`); "
            "`io.read(\"l\")` a line without the newline (nil at EOF), `io.read(\"n\")` a number (skips blanks, nil on "
            "failure), `io.read(\"a\")` everything; mixing read(\"n\") then read(\"l\") leaves the rest of the line (the "
            "newline) unread. `io.write(...)` does not add a newline. Multiple results: `(s:gsub(a, b))` in parentheses "
            "keeps one value.\n"
            "- Tables: `#t` is only reliable for sequences without holes; `table.insert(t, pos, v)`, `table.remove(t, i)`, "
            "`table.sort(t, function(a, b) return a < b end)` (comparator must be a strict order, never `<=`; not stable: "
            "break ties explicitly), `table.concat(t, \", \")`, `table.unpack(t, 1, n)`, `table.move`. Patterns are not "
            "regex: `%d %a %s %w %p`, `-` is lazy `*`, `%b()`, no `|` alternation, escape with `%`. `#s` is bytes (utf8.len for characters). "
            "`os.time{year=2024, month=3, day=1, hour=12}`, `os.date(\"%Y-%m-%d\", t)`."),
        "topics": [],
    },
}
